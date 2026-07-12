import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.generation.providers.registry import build_default_provider_registry
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.handlers import handle_ingest_collect
from app.jobs.registry import JobContext, JobHandlerRegistry
from app.jobs.types import JobErrorClass
from app.jobs.worker import WorkerRunner


class FakeSession:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.events.append(("commit", id(self)))

    async def rollback(self):
        self.events.append(("rollback", id(self)))


class SessionFactory:
    def __init__(self, events):
        self.events = events
        self.sessions = []

    def __call__(self):
        session = FakeSession(self.events)
        self.sessions.append(session)
        return session


class SharedRepositoryState:
    def __init__(self, job):
        self.job = job
        self.claim_allowed = None
        self.claim_session = None
        self.heartbeat_sessions = []
        self.finished = []
        self.failed = []


class FakeRepository:
    def __init__(self, session, state):
        self.session = session
        self.state = state

    async def claim_next_job(self, *, allowed_job_types, **kwargs):
        self.state.claim_allowed = allowed_job_types
        self.state.claim_session = self.session
        job, self.state.job = self.state.job, None
        return job

    async def heartbeat_job(self, **kwargs):
        self.state.heartbeat_sessions.append(self.session)
        return True

    async def finish_job(self, **kwargs):
        self.state.finished.append(kwargs)

    async def fail_job(self, **kwargs):
        self.state.failed.append(kwargs)


class RuntimeRecorder:
    def __init__(self, session, records):
        self.session = session
        self.records = records

    async def record(self, *args, **kwargs):
        self.records.append((self.session, args, kwargs))


def _job(job_type="ingest.collect", payload=None):
    return SimpleNamespace(
        id=uuid4(),
        job_type=job_type,
        payload=payload or {},
        attempt_count=1,
        max_attempts=3,
    )


def _runner(job, handler=None):
    events = []
    sessions = SessionFactory(events)
    state = SharedRepositoryState(job)
    runtime_records = []
    registry = JobHandlerRegistry()
    if handler is not None:
        registry.register(job.job_type, handler)
    runner = WorkerRunner(
        session_factory=sessions,
        handler_registry=registry,
        provider_registry=build_default_provider_registry(),
        repository_factory=lambda session: FakeRepository(session, state),
        runtime_service_factory=lambda session: RuntimeRecorder(session, runtime_records),
        worker_id="worker-test",
        clock=lambda: datetime(2026, 7, 11, 8, 0, tzinfo=UTC),
        heartbeat_seconds=3600,
    )
    return runner, state, sessions, events, runtime_records


@pytest.mark.asyncio
async def test_run_once_returns_false_when_no_job_and_passes_allowed_types_unchanged():
    runner, state, _, _, runtime = _runner(None)

    result = await runner.run_once(allowed_job_types=("ingest.collect",))

    assert result is False
    assert state.claim_allowed == ("ingest.collect",)
    assert runtime[0][2]["observed_at"] == datetime(2026, 7, 11, 8, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_claim_commits_before_handler_and_lease_heartbeat_uses_independent_session():
    job = _job()
    observed = {}

    async def handler(claimed, context):
        observed["commit_seen"] = ("commit", id(context.session)) in events
        return {"checked": 1}

    runner, state, _, events, _ = _runner(job, handler)

    assert await runner.run_once(allowed_job_types=("ingest.collect",)) is True
    assert observed["commit_seen"] is True
    assert state.heartbeat_sessions
    assert all(session is not state.claim_session for session in state.heartbeat_sessions)
    assert state.finished[0]["result"] == {"checked": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "error_class", "code"),
    [
        (RetryableJobError(code="temporary", message="try later"), JobErrorClass.RETRYABLE, "temporary"),
        (NeedsReviewJobError(code="ambiguous", message="review"), JobErrorClass.NEEDS_REVIEW, "ambiguous"),
        (PermanentJobError(code="invalid", message="bad input"), JobErrorClass.PERMANENT, "invalid"),
    ],
)
async def test_known_handler_failures_map_to_exact_error_classes(error, error_class, code):
    async def handler(job, context):
        raise error

    runner, state, _, _, _ = _runner(_job(), handler)
    await runner.run_once(allowed_job_types=("ingest.collect",))

    assert state.failed[0]["error_class"] == error_class
    assert state.failed[0]["error_code"] == code
    assert state.failed[0]["error_message"] == error.message


@pytest.mark.asyncio
async def test_retryable_handler_can_supply_exact_retry_time_and_default_stays_thirty_seconds():
    retry_at = datetime(2026, 7, 11, 8, 7, tzinfo=UTC)

    async def explicit_handler(job, context):
        raise RetryableJobError(code="rate_limited", retry_at=retry_at)

    explicit_runner, explicit_state, _, _, _ = _runner(_job(), explicit_handler)
    await explicit_runner.run_once(allowed_job_types=("ingest.collect",))
    assert explicit_state.failed[0]["retry_at"] == retry_at

    async def fallback_handler(job, context):
        raise RetryableJobError(code="temporary")

    fallback_runner, fallback_state, _, _, _ = _runner(_job(), fallback_handler)
    await fallback_runner.run_once(allowed_job_types=("ingest.collect",))
    assert fallback_state.failed[0]["retry_at"] == datetime(2026, 7, 11, 8, 0, 30, tzinfo=UTC)


def test_retryable_error_rejects_naive_retry_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        RetryableJobError(code="temporary", retry_at=datetime(2026, 7, 11, 8, 0))


@pytest.mark.asyncio
async def test_unknown_explicitly_allowed_type_is_permanent_and_unexpected_is_retryable():
    unknown_runner, unknown_state, _, _, _ = _runner(_job("missing"))
    await unknown_runner.run_once(allowed_job_types=("missing",))
    assert unknown_state.failed[0]["error_class"] == JobErrorClass.PERMANENT
    assert unknown_state.failed[0]["error_code"] == "unknown_job_type"

    async def broken(job, context):
        raise RuntimeError("secret payload must not escape")

    broken_runner, broken_state, _, _, _ = _runner(_job(), broken)
    await broken_runner.run_once(allowed_job_types=("ingest.collect",))
    assert broken_state.failed[0]["error_class"] == JobErrorClass.RETRYABLE
    assert broken_state.failed[0]["error_code"] == "unhandled_exception"
    assert "secret payload" not in broken_state.failed[0]["error_message"]


@pytest.mark.asyncio
async def test_process_cancellation_waits_for_active_handler_boundary_then_finishes_job():
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(job, context):
        started.set()
        await release.wait()
        return {"checked": 1}

    runner, state, _, _, _ = _runner(_job(), handler)
    task = asyncio.create_task(runner.run_once(allowed_job_types=("ingest.collect",)))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert task.done() is False

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.finished[0]["result"] == {"checked": 1}


@pytest.mark.asyncio
async def test_ingest_handler_passes_only_locked_arguments_and_returns_success(monkeypatch):
    calls = []

    class FakeWorkflow:
        async def run(self, **kwargs):
            calls.append(kwargs)
            return {"failed": 0, "checked": 2}

    monkeypatch.setattr("app.jobs.handlers._build_workflow", FakeWorkflow)
    context = JobContext(session=object(), providers=build_default_provider_registry())
    job = _job(payload={"platforms": ["rss"], "source_ids": ["source-1"], "ignored": "value"})

    result = await handle_ingest_collect(job, context)

    assert result == {"failed": 0, "checked": 2}
    assert calls == [
        {
            "session": context.session,
            "platforms": ["rss"],
            "source_ids": ["source-1"],
            "trigger": "workflow_job",
        }
    ]


@pytest.mark.asyncio
async def test_ingest_handler_maps_partial_stats_to_retryable_failure(monkeypatch):
    class FakeWorkflow:
        async def run(self, **kwargs):
            return {"failed": 1, "errors": [{"source": "one"}]}

    monkeypatch.setattr("app.jobs.handlers._build_workflow", FakeWorkflow)
    context = JobContext(session=object(), providers=build_default_provider_registry())

    with pytest.raises(RetryableJobError) as caught:
        await handle_ingest_collect(_job(), context)
    assert caught.value.code == "ingest_partial"
