from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.db.models import Source
from app.db.session import async_session
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowSchedule
from app.jobs.repository import JobRepository
from app.jobs.runtime import RuntimeHeartbeatService, build_component_id
from app.jobs.types import JobOrigin

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SchedulerTickResult:
    expired_leases: int
    reconciled: int
    enqueued: int
    deduplicated: int
    invalid: int
    paused: bool


def build_due_schedule_statement(now: datetime) -> Select[tuple[WorkflowSchedule]]:
    return (
        select(WorkflowSchedule)
        .where(
            WorkflowSchedule.enabled.is_(True),
            WorkflowSchedule.next_run_at.is_not(None),
            WorkflowSchedule.next_run_at <= now,
        )
        .order_by(WorkflowSchedule.next_run_at, WorkflowSchedule.created_at)
        .with_for_update(skip_locked=True)
    )


def _aware(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _parse_local_time(value: str) -> time:
    parsed = datetime.strptime(value, "%H:%M")
    if parsed.strftime("%H:%M") != value:
        raise ValueError("local_time must use zero-padded HH:MM")
    return parsed.time()


def _next_daily_run(*, after: datetime, timezone: str, local_time: str) -> datetime:
    zone = ZoneInfo(timezone)
    scheduled_time = _parse_local_time(local_time)
    local_after = _aware(after, name="after").astimezone(zone)
    candidate = datetime.combine(local_after.date(), scheduled_time, tzinfo=zone)
    if candidate <= local_after:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


class SchedulerService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: JobRepository | None = None,
        settings: Settings = settings,
    ) -> None:
        self.session = session
        self.repository = repository or JobRepository(session)
        self.settings = settings
        self._timezone = ZoneInfo(settings.scheduler_timezone)
        self._daily_time = _parse_local_time(settings.daily_collection_time)

    async def tick(self, now: datetime | None = None) -> SchedulerTickResult:
        observed_at = _aware(now or datetime.now(UTC), name="now")
        async with self.session.begin():
            expired = await self.repository.requeue_expired_leases(now=observed_at)
            reconciled, invalid = await self._reconcile_sources(observed_at)
            if await self._is_paused():
                return SchedulerTickResult(expired, reconciled, 0, 0, invalid, True)

            enqueued = 0
            deduplicated = 0
            for schedule in await self._lock_due_schedules(observed_at):
                if not self._valid_schedule(schedule, observed_at):
                    invalid += 1
                    continue
                due_time = schedule.next_run_at
                if due_time is None:  # pragma: no cover - due query excludes nulls
                    continue
                result = await self.repository.enqueue_job(
                    job_type=schedule.job_type,
                    payload=dict(schedule.payload),
                    idempotency_key=f"schedule:{schedule.id}:{due_time.isoformat()}",
                    origin=JobOrigin.SCHEDULER,
                    scheduled_for=due_time,
                    pause_sensitive=schedule.pause_sensitive,
                )
                if result.created:
                    enqueued += 1
                else:
                    deduplicated += 1
                schedule.last_enqueued_at = due_time
                schedule.next_run_at = self._advance_schedule(schedule, due_time)
                if schedule.source_id is not None:
                    source = next(
                        (item for item in await self._list_sources() if item.id == schedule.source_id),
                        None,
                    )
                    if source is not None:
                        source.next_fetch_at = schedule.next_run_at
            await self.session.flush()
            return SchedulerTickResult(expired, reconciled, enqueued, deduplicated, invalid, False)

    async def _reconcile_sources(self, now: datetime) -> tuple[int, int]:
        reconciled = 0
        invalid = 0
        for source in await self._list_sources():
            key = f"source:{source.id}"
            schedule = await self._get_schedule(key)
            if schedule is None:
                schedule = self._new_source_schedule(source, now)
                await self._persist_schedule(schedule)
            elif not source.active or bool(source.disabled_reason):
                schedule.enabled = False
                source.next_fetch_at = None
            elif not self._valid_schedule(schedule, now):
                source.next_fetch_at = None
                invalid += 1
            else:
                self._refresh_source_schedule(schedule, source, now)
            reconciled += 1
        await self.session.flush()
        return reconciled, invalid

    def _new_source_schedule(self, source: Source, now: datetime) -> WorkflowSchedule:
        enabled = bool(source.active and not source.disabled_reason)
        daily = source.fetch_interval_minutes == 1440
        next_run = None
        if enabled:
            if daily:
                next_run = _next_daily_run(
                    after=now,
                    timezone=self.settings.scheduler_timezone,
                    local_time=self.settings.daily_collection_time,
                )
            else:
                base = max(now, source.last_fetch_at) if source.last_fetch_at is not None else now
                next_run = base + timedelta(minutes=source.fetch_interval_minutes)
        source.next_fetch_at = next_run
        return WorkflowSchedule(
            id=uuid4(),
            schedule_key=f"source:{source.id}",
            source_id=source.id,
            name=f"Collect {source.name}",
            job_type="ingest.collect",
            payload={"source_ids": [str(source.id)], "platforms": None},
            schedule_kind="daily" if daily else "interval",
            timezone=self.settings.scheduler_timezone,
            local_time=self.settings.daily_collection_time if daily else None,
            interval_minutes=None if daily else source.fetch_interval_minutes,
            next_run_at=next_run,
            enabled=enabled,
            pause_sensitive=True,
        )

    def _refresh_source_schedule(self, schedule: WorkflowSchedule, source: Source, now: datetime) -> None:
        schedule.enabled = True
        if source.fetch_interval_minutes == 1440:
            config_changed = (
                schedule.schedule_kind != "daily"
                or schedule.timezone != self.settings.scheduler_timezone
                or schedule.local_time != self.settings.daily_collection_time
                or schedule.interval_minutes is not None
            )
            schedule.schedule_kind = "daily"
            schedule.timezone = self.settings.scheduler_timezone
            schedule.local_time = self.settings.daily_collection_time
            schedule.interval_minutes = None
            if config_changed or schedule.next_run_at is None:
                schedule.next_run_at = _next_daily_run(
                    after=now,
                    timezone=schedule.timezone,
                    local_time=schedule.local_time or "",
                )
        else:
            config_changed = (
                schedule.schedule_kind != "interval"
                or schedule.timezone != self.settings.scheduler_timezone
                or schedule.local_time is not None
                or schedule.interval_minutes != source.fetch_interval_minutes
            )
            schedule.schedule_kind = "interval"
            schedule.timezone = self.settings.scheduler_timezone
            schedule.local_time = None
            schedule.interval_minutes = source.fetch_interval_minutes
            fetched_next = (
                source.last_fetch_at + timedelta(minutes=source.fetch_interval_minutes)
                if source.last_fetch_at is not None
                else None
            )
            if config_changed or schedule.next_run_at is None:
                schedule.next_run_at = max(now, source.last_fetch_at or now) + timedelta(
                    minutes=source.fetch_interval_minutes
                )
            elif fetched_next is not None and fetched_next > schedule.next_run_at:
                schedule.next_run_at = fetched_next
        schedule.payload = {"source_ids": [str(source.id)], "platforms": None}
        source.next_fetch_at = schedule.next_run_at

    def _valid_schedule(self, schedule: WorkflowSchedule, now: datetime) -> bool:
        try:
            ZoneInfo(schedule.timezone)
            if schedule.schedule_kind == "daily":
                if schedule.local_time is None:
                    raise ValueError("daily schedule is missing local_time")
                _parse_local_time(schedule.local_time)
            elif schedule.schedule_kind == "interval":
                if schedule.interval_minutes is None or schedule.interval_minutes <= 0:
                    raise ValueError("interval schedule must have a positive interval")
            else:
                raise ValueError("unsupported schedule kind")
        except (ValueError, ZoneInfoNotFoundError) as exc:
            schedule.enabled = False
            self.session.add(
                WorkflowEvent(
                    workflow_job_id=None,
                    event_type="schedule.invalid",
                    actor="scheduler",
                    event_data=redact_event_data(
                        {"schedule_id": str(schedule.id), "schedule_key": schedule.schedule_key, "reason": str(exc)}
                    ),
                    created_at=now,
                )
            )
            return False
        return True

    @staticmethod
    def _advance_schedule(schedule: WorkflowSchedule, due_time: datetime) -> datetime:
        if schedule.schedule_kind == "daily":
            return _next_daily_run(
                after=due_time + timedelta(microseconds=1),
                timezone=schedule.timezone,
                local_time=schedule.local_time or "",
            )
        if schedule.interval_minutes is None:  # pragma: no cover - validated before advancing
            raise ValueError("interval schedule is missing interval_minutes")
        return due_time + timedelta(minutes=schedule.interval_minutes)

    async def _list_sources(self) -> list[Source]:
        return list(await self.session.scalars(select(Source).order_by(Source.name)))

    async def _get_schedule(self, schedule_key: str) -> WorkflowSchedule | None:
        return await self.session.scalar(
            select(WorkflowSchedule).where(WorkflowSchedule.schedule_key == schedule_key)
        )

    async def _persist_schedule(self, schedule: WorkflowSchedule) -> None:
        self.session.add(schedule)
        await self.session.flush()

    async def _is_paused(self) -> bool:
        return bool(
            await self.session.scalar(
                select(AutomationControl.global_pause).where(AutomationControl.id == "global")
            )
        )

    async def _lock_due_schedules(self, now: datetime) -> list[WorkflowSchedule]:
        return list(await self.session.scalars(build_due_schedule_statement(now)))


async def run_scheduler() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    component_id = build_component_id("scheduler")
    async with async_session() as session:
        await RuntimeHeartbeatService(session).record(
            component_id=component_id,
            component_type="scheduler",
            capabilities=("scheduling",),
            observed_at=datetime.now(UTC),
            metadata={},
        )
        await session.commit()

    while not stop.is_set():
        async with async_session() as heartbeat_session:
            await RuntimeHeartbeatService(heartbeat_session).record(
                component_id=component_id,
                component_type="scheduler",
                capabilities=("scheduling",),
                observed_at=datetime.now(UTC),
                metadata={},
            )
            await heartbeat_session.commit()
        async with async_session() as session:
            result = await SchedulerService(session).tick()
            logger.info(
                "scheduler tick expired=%d reconciled=%d enqueued=%d deduplicated=%d invalid=%d paused=%s",
                result.expired_leases,
                result.reconciled,
                result.enqueued,
                result.deduplicated,
                result.invalid,
                result.paused,
            )
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.scheduler_poll_seconds)
        except TimeoutError:
            pass


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
