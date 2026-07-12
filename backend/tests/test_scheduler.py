from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.config import Settings
from app.jobs.scheduler import SchedulerService, build_due_schedule_statement


class Transaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.events.append("begin")

    async def __aexit__(self, exc_type, exc, tb):
        self.session.events.append("rollback" if exc else "commit")


class FakeSession:
    def __init__(self):
        self.events = []

    def begin(self):
        return Transaction(self)

    def add(self, value):
        self.events.append(("add", getattr(value, "event_type", None)))

    async def flush(self):
        return None


class FakeJobRepository:
    def __init__(self):
        self.requeues = 0
        self.enqueued = []
        self.enqueue_created = True

    async def requeue_expired_leases(self, *, now):
        self.requeues += 1
        return 0

    async def enqueue_job(self, **kwargs):
        self.enqueued.append(kwargs)
        return SimpleNamespace(created=self.enqueue_created)


class MemoryScheduler(SchedulerService):
    def __init__(self, *, sources, paused=False):
        self.fake_session = FakeSession()
        self.fake_jobs = FakeJobRepository()
        super().__init__(self.fake_session, repository=self.fake_jobs, settings=Settings())
        self.sources = sources
        self.schedules = {}
        self.paused = paused

    async def _list_sources(self):
        return self.sources

    async def _get_schedule(self, schedule_key):
        return self.schedules.get(schedule_key)

    async def _persist_schedule(self, schedule):
        self.schedules[schedule.schedule_key] = schedule

    async def _is_paused(self):
        return self.paused

    async def _lock_due_schedules(self, now):
        return [
            schedule
            for schedule in self.schedules.values()
            if schedule.enabled and schedule.next_run_at is not None and schedule.next_run_at <= now
        ]


def _source(*, minutes=1440, active=True, last_fetch_at=None):
    return SimpleNamespace(
        id=uuid4(),
        name="Source",
        active=active,
        disabled_reason=None,
        fetch_interval_minutes=minutes,
        last_fetch_at=last_fetch_at,
        next_fetch_at=None,
    )


def test_scheduler_settings_have_exact_defaults_and_validation():
    value = Settings()
    assert value.scheduler_timezone == "Asia/Tehran"
    assert value.daily_collection_time == "06:00"
    assert value.scheduler_poll_seconds == 15.0
    assert value.worker_poll_seconds == 1.0
    assert value.worker_lease_seconds == 120
    assert value.worker_heartbeat_seconds == 30
    with pytest.raises(ValidationError):
        Settings(scheduler_timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        Settings(daily_collection_time="6am")
    with pytest.raises(ValidationError):
        Settings(daily_collection_time="6:00")


@pytest.mark.asyncio
async def test_daily_source_reconciles_to_tehran_0600_across_date_boundary():
    source = _source()
    service = MemoryScheduler(sources=[source])
    now = datetime(2026, 7, 11, 3, 0, tzinfo=UTC)  # 06:30 in Tehran

    await service.tick(now)

    schedule = service.schedules[f"source:{source.id}"]
    assert schedule.schedule_kind == "daily"
    assert schedule.timezone == "Asia/Tehran"
    assert schedule.local_time == "06:00"
    assert schedule.next_run_at == datetime(2026, 7, 12, 2, 30, tzinfo=UTC)
    assert source.next_fetch_at == schedule.next_run_at


@pytest.mark.asyncio
async def test_interval_uses_latest_initial_observation_and_last_fetch():
    source = _source(minutes=30, last_fetch_at=datetime(2026, 7, 11, 8, 5, tzinfo=UTC))
    service = MemoryScheduler(sources=[source])
    now = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)

    await service.tick(now)

    schedule = service.schedules[f"source:{source.id}"]
    assert schedule.schedule_kind == "interval"
    assert schedule.interval_minutes == 30
    assert schedule.next_run_at == datetime(2026, 7, 11, 8, 35, tzinfo=UTC)


@pytest.mark.asyncio
async def test_interval_to_daily_restores_daily_config_and_recomputes_stale_next_run():
    source = _source(minutes=30)
    service = MemoryScheduler(sources=[source])
    first_observation = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    await service.tick(first_observation)
    schedule = service.schedules[f"source:{source.id}"]
    stale_interval_run = schedule.next_run_at

    source.fetch_interval_minutes = 1440
    second_observation = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
    await service.tick(second_observation)

    assert schedule.schedule_kind == "daily"
    assert schedule.timezone == "Asia/Tehran"
    assert schedule.local_time == "06:00"
    assert schedule.interval_minutes is None
    assert schedule.next_run_at == datetime(2026, 7, 12, 2, 30, tzinfo=UTC)
    assert schedule.next_run_at != stale_interval_run
    assert source.next_fetch_at == schedule.next_run_at


@pytest.mark.asyncio
async def test_daily_to_interval_clears_daily_config_and_recomputes_from_latest_observation():
    source = _source(minutes=1440)
    service = MemoryScheduler(sources=[source])
    await service.tick(datetime(2026, 7, 11, 1, 0, tzinfo=UTC))
    schedule = service.schedules[f"source:{source.id}"]
    stale_daily_run = schedule.next_run_at

    source.fetch_interval_minutes = 30
    observation = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    await service.tick(observation)

    assert schedule.schedule_kind == "interval"
    assert schedule.local_time is None
    assert schedule.interval_minutes == 30
    assert schedule.next_run_at == observation + timedelta(minutes=30)
    assert schedule.next_run_at != stale_daily_run
    assert source.next_fetch_at == schedule.next_run_at


@pytest.mark.asyncio
async def test_due_schedule_enqueues_and_advances_atomically_then_deduplicates_next_tick():
    source = _source(minutes=30)
    service = MemoryScheduler(sources=[source])
    now = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    await service.tick(now)
    schedule = service.schedules[f"source:{source.id}"]
    due_time = now + timedelta(minutes=30)
    schedule.next_run_at = due_time

    await service.tick(due_time)
    await service.tick(due_time)

    assert len(service.fake_jobs.enqueued) == 1
    call = service.fake_jobs.enqueued[0]
    assert call["job_type"] == "ingest.collect"
    assert call["payload"] == {"source_ids": [str(source.id)], "platforms": None}
    assert call["idempotency_key"] == f"schedule:{schedule.id}:{due_time.isoformat()}"
    assert call["origin"].value == "scheduler"
    assert schedule.last_enqueued_at == due_time
    assert source.next_fetch_at == due_time + timedelta(minutes=30)
    assert service.fake_session.events.count("begin") == service.fake_session.events.count("commit")


@pytest.mark.asyncio
async def test_due_schedule_created_false_counts_dedup_and_still_advances_durable_schedule():
    source = _source(minutes=30)
    service = MemoryScheduler(sources=[source])
    now = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    await service.tick(now)
    schedule = service.schedules[f"source:{source.id}"]
    due_time = schedule.next_run_at
    service.fake_jobs.enqueue_created = False

    result = await service.tick(due_time)

    assert result.enqueued == 0
    assert result.deduplicated == 1
    assert len(service.fake_jobs.enqueued) == 1
    assert schedule.last_enqueued_at == due_time
    assert schedule.next_run_at == due_time + timedelta(minutes=30)
    assert source.next_fetch_at == schedule.next_run_at


@pytest.mark.asyncio
async def test_pause_requeues_expired_leases_but_does_not_materialize_due_schedule():
    source = _source(minutes=30)
    service = MemoryScheduler(sources=[source], paused=True)
    now = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    await service.tick(now)
    service.schedules[f"source:{source.id}"].next_run_at = now

    await service.tick(now)

    assert service.fake_jobs.requeues == 2
    assert service.fake_jobs.enqueued == []


@pytest.mark.asyncio
async def test_disabled_source_disables_schedule_and_invalid_values_emit_event():
    source = _source(active=False)
    service = MemoryScheduler(sources=[source])
    now = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    await service.tick(now)
    schedule = service.schedules[f"source:{source.id}"]
    assert schedule.enabled is False

    source.active = True
    schedule.enabled = True
    schedule.timezone = "bad/timezone"
    schedule.local_time = "invalid"
    schedule.schedule_kind = "daily"
    schedule.next_run_at = now
    await service.tick(now)

    assert schedule.enabled is False
    assert ("add", "schedule.invalid") in service.fake_session.events
    assert service.fake_jobs.enqueued == []


@pytest.mark.asyncio
async def test_non_zero_padded_durable_daily_time_disables_schedule_and_emits_invalid_event():
    source = _source()
    service = MemoryScheduler(sources=[source])
    now = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    await service.tick(now)
    schedule = service.schedules[f"source:{source.id}"]
    schedule.local_time = "6:00"
    schedule.next_run_at = now

    await service.tick(now)

    assert schedule.enabled is False
    assert source.next_fetch_at is None
    assert ("add", "schedule.invalid") in service.fake_session.events
    assert service.fake_jobs.enqueued == []


def test_due_schedule_query_locks_with_skip_locked():
    sql = str(build_due_schedule_statement(datetime(2026, 7, 11, tzinfo=UTC)).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
