import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.generation.providers.registry import build_default_provider_registry
from app.jobs import worker as worker_module
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.handlers import handle_ingest_collect
from app.jobs.registry import JobContext, JobHandlerRegistry
from app.jobs.types import JobErrorClass, JobOrigin
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
async def test_run_once_returns_false_when_no_job_and_claims_only_registry_types():
    runner, state, _, _, runtime = _runner(None)

    result = await runner.run_once()

    assert result is False
    assert state.claim_allowed == ()
    assert runtime[0][2]["observed_at"] == datetime(2026, 7, 11, 8, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_claim_commits_before_handler_and_lease_heartbeat_uses_independent_session():
    job = _job()
    observed = {}

    async def handler(claimed, context):
        observed["commit_seen"] = ("commit", id(context.session)) in events
        return {"checked": 1}

    runner, state, _, events, _ = _runner(job, handler)

    assert await runner.run_once() is True
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
    await runner.run_once()

    assert state.failed[0]["error_class"] == error_class
    assert state.failed[0]["error_code"] == code
    assert state.failed[0]["error_message"] == error.message


@pytest.mark.asyncio
async def test_retryable_handler_can_supply_exact_retry_time_and_default_stays_thirty_seconds():
    retry_at = datetime(2026, 7, 11, 8, 7, tzinfo=UTC)

    async def explicit_handler(job, context):
        raise RetryableJobError(code="rate_limited", retry_at=retry_at)

    explicit_runner, explicit_state, _, _, _ = _runner(_job(), explicit_handler)
    await explicit_runner.run_once()
    assert explicit_state.failed[0]["retry_at"] == retry_at

    async def fallback_handler(job, context):
        raise RetryableJobError(code="temporary")

    fallback_runner, fallback_state, _, _, _ = _runner(_job(), fallback_handler)
    await fallback_runner.run_once()
    assert fallback_state.failed[0]["retry_at"] == datetime(2026, 7, 11, 8, 0, 30, tzinfo=UTC)


def test_retryable_error_rejects_naive_retry_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        RetryableJobError(code="temporary", retry_at=datetime(2026, 7, 11, 8, 0))


@pytest.mark.asyncio
async def test_unexpected_handler_failure_is_retryable_without_leaking_details():
    async def broken(job, context):
        raise RuntimeError("secret payload must not escape")

    broken_runner, broken_state, _, events, _ = _runner(_job(), broken)
    await broken_runner.run_once()
    assert broken_state.failed[0]["error_class"] == JobErrorClass.RETRYABLE
    assert broken_state.failed[0]["error_code"] == "unhandled_exception"
    assert "secret payload" not in broken_state.failed[0]["error_message"]
    assert any(event[0] == "rollback" for event in events)


@pytest.mark.asyncio
async def test_process_cancellation_waits_for_active_handler_boundary_then_finishes_job():
    started = asyncio.Event()
    release = asyncio.Event()

    async def handler(job, context):
        started.set()
        await release.wait()
        return {"checked": 1}

    runner, state, _, _, _ = _runner(_job(), handler)
    task = asyncio.create_task(runner.run_once())
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
    followups = []

    class FakeWorkflow:
        async def run(self, **kwargs):
            calls.append(kwargs)
            return {"failed": 0, "checked": 2}

    class FakeJobs:
        async def enqueue_job(self, **kwargs):
            followups.append(kwargs)

    monkeypatch.setattr("app.jobs.handlers._build_workflow", FakeWorkflow)
    monkeypatch.setattr("app.jobs.handlers._build_job_repository", lambda session: FakeJobs())
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
    assert followups == [
        {
            "job_type": "story.group_pending",
            "payload": {"limit": 100, "root_ingest_job_id": str(job.id)},
            "idempotency_key": f"story-group:{job.id}",
            "origin": JobOrigin.AUTOMATION,
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


def test_cli_accepts_repeatable_semantic_capabilities():
    assert worker_module.parse_capabilities(
        ["--capability", "ingestion", "--capability", "source", "--capability", "generation"]
    ) == ("ingestion", "source", "generation")


@pytest.mark.parametrize(
    ("capabilities", "expected_builders"),
    [
        (("ingestion",), ()),
        (("source",), ("source",)),
        (("generation",), ("generation",)),
        (("publishing",), ("publishing",)),
    ],
)
def test_each_capability_constructs_only_its_permitted_dependency_bundle(
    monkeypatch, capabilities, expected_builders
):
    constructed = []
    captured = {}

    def bundle(name, values):
        def build(owner):
            constructed.append(name)
            return values

        return build

    monkeypatch.setattr(
        "app.jobs.worker._build_source_dependencies",
        bundle("source", {"source_registry": object(), "media_stager": object()}),
    )
    monkeypatch.setattr(
        "app.jobs.worker._build_generation_dependencies",
        bundle("generation", {"profile_resolver": object()}),
    )
    monkeypatch.setattr(
        "app.jobs.worker._build_publishing_dependencies",
        bundle(
            "publishing",
            {"telegram_client": object(), "destination_secret_resolver": object()},
        ),
    )

    def fake_registry(**kwargs):
        captured.update(kwargs)
        return JobHandlerRegistry()

    monkeypatch.setattr("app.jobs.worker.build_default_registry", fake_registry)

    runner = worker_module.build_worker_runner(capabilities)

    assert tuple(constructed) == expected_builders
    assert captured["capabilities"] == capabilities
    assert runner.capabilities == capabilities


def test_publishing_never_constructs_source_or_openrouter_dependencies(monkeypatch):
    monkeypatch.setattr(
        "app.jobs.worker._build_source_dependencies",
        lambda owner: pytest.fail("MTProto constructed"),
    )
    monkeypatch.setattr(
        "app.jobs.worker._build_generation_dependencies",
        lambda owner: pytest.fail("OpenRouter constructed"),
    )
    monkeypatch.setattr(
        "app.jobs.worker._build_publishing_dependencies",
        lambda owner: {"telegram_client": object(), "destination_secret_resolver": object()},
    )
    monkeypatch.setattr("app.jobs.worker.build_default_registry", lambda **kwargs: JobHandlerRegistry())

    worker_module.build_worker_runner(("publishing",))


def test_publishing_never_resolves_export_root(monkeypatch):
    class PublishingSettings:
        @property
        def export_root(self):
            pytest.fail("publishing must not resolve EXPORT_ROOT")

    monkeypatch.setattr(worker_module, "settings", PublishingSettings())
    monkeypatch.setattr(
        "app.jobs.worker._build_publishing_dependencies",
        lambda owner: {"telegram_client": object(), "destination_secret_resolver": object()},
    )
    monkeypatch.setattr("app.jobs.worker.build_default_registry", lambda **kwargs: JobHandlerRegistry())

    worker_module.build_worker_runner(("publishing",))


def test_source_generation_never_constructs_bot_api_or_resolves_destination_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DESTINATION_NEWS_TOKEN", "must-not-be-read")
    monkeypatch.setattr(
        "app.jobs.worker._build_publishing_dependencies",
        lambda owner: pytest.fail("Bot API constructed"),
    )
    monkeypatch.setattr(
        "app.jobs.worker._build_source_dependencies",
        lambda owner: {"source_registry": object(), "media_stager": object()},
    )
    monkeypatch.setattr(
        "app.jobs.worker._build_generation_dependencies",
        lambda owner: {"profile_resolver": object()},
    )
    monkeypatch.setattr("app.jobs.worker.build_default_registry", lambda **kwargs: JobHandlerRegistry())

    worker_module.build_worker_runner(("source", "generation"))


@pytest.mark.asyncio
async def test_future_registered_handler_automatically_enters_atomic_claim_set():
    runner, state, _, _, _ = _runner(None)

    async def execute_retention(job, context):
        return {}

    runner.handler_registry.register("execute_retention", execute_retention)

    await runner.run_once()

    assert state.claim_allowed == ("execute_retention",)


def test_main_builds_worker_from_cli_capabilities(monkeypatch):
    observed = {}

    async def fake_run_worker(capabilities):
        observed["capabilities"] = capabilities

    monkeypatch.setattr("app.jobs.worker.run_worker", fake_run_worker)
    monkeypatch.setattr(
        sys,
        "argv",
        ["worker", "--capability", "publishing"],
    )

    from app.jobs.worker import main

    main()

    assert observed["capabilities"] == ("publishing",)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("transport failed"), asyncio.CancelledError()])
async def test_media_stager_removes_partial_tree_when_materialization_raises(
    monkeypatch, tmp_path, failure
):
    monkeypatch.setattr(
        worker_module,
        "settings",
        SimpleNamespace(
            telegram_media_staging_root=str(tmp_path / "staging"),
            media_root=str(tmp_path / "media"),
            telegram_max_photo_bytes=100,
            telegram_max_file_bytes=100,
        ),
    )
    stager = worker_module._TelegramMediaStager()

    class PartialAdapter:
        async def materialize_media(self, envelope, staging_dir):
            nested = staging_dir / "nested"
            nested.mkdir()
            (nested / "partial.bin").write_bytes(b"partial")
            raise failure

    with pytest.raises(type(failure)):
        await stager.materialize(PartialAdapter(), object())

    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.asyncio
async def test_media_stager_recursively_removes_dirty_empty_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        worker_module,
        "settings",
        SimpleNamespace(
            telegram_media_staging_root=str(tmp_path / "staging"),
            media_root=str(tmp_path / "media"),
            telegram_max_photo_bytes=100,
            telegram_max_file_bytes=100,
        ),
    )
    stager = worker_module._TelegramMediaStager()

    class DirtyEmptyAdapter:
        async def materialize_media(self, envelope, staging_dir):
            (staging_dir / "unexpected.tmp").write_bytes(b"dirty")
            return ()

    assert await stager.materialize(DirtyEmptyAdapter(), object()) == ()
    assert list((tmp_path / "staging").iterdir()) == []


@pytest.mark.asyncio
async def test_http_client_owner_reuses_same_configuration_is_bounded_and_closes_all():
    clients = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            clients.append(self)

        async def aclose(self):
            self.closed = True

    owner = worker_module.HttpClientOwner(client_factory=FakeClient, max_clients=2)

    first = owner.get("openrouter", base_url="https://one.example", timeout=10)
    assert owner.get("openrouter", base_url="https://one.example", timeout=10) is first
    owner.get("openrouter", base_url="https://two.example", timeout=10)
    with pytest.raises(RuntimeError, match="limit"):
        owner.get("openrouter", base_url="https://three.example", timeout=10)

    assert len(clients) == 2
    await owner.aclose()
    assert all(client.closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [None, RuntimeError("worker failed"), asyncio.CancelledError()],
)
async def test_run_worker_closes_resources_on_success_error_and_cancellation(monkeypatch, failure):
    events = []

    class FakeRunner:
        async def run_forever(self, *, stop):
            events.append("run")
            if failure is not None:
                raise failure

        async def close(self):
            events.append("close")

    monkeypatch.setattr(
        "app.jobs.worker.build_worker_runner",
        lambda capabilities, resource_owner: FakeRunner(),
    )

    if failure is None:
        await worker_module.run_worker(("ingestion",))
    else:
        with pytest.raises(type(failure)):
            await worker_module.run_worker(("ingestion",))

    assert events == ["run", "close"]


@pytest.mark.asyncio
async def test_run_worker_closes_owner_when_dependency_construction_fails(monkeypatch):
    events = []

    class FakeOwner:
        async def aclose(self):
            events.append("close")

    owner = FakeOwner()
    monkeypatch.setattr("app.jobs.worker.HttpClientOwner", lambda: owner)

    def fail_build(capabilities, resource_owner):
        assert resource_owner is owner
        raise RuntimeError("dependency construction failed")

    monkeypatch.setattr("app.jobs.worker.build_worker_runner", fail_build)

    with pytest.raises(RuntimeError, match="dependency construction"):
        await worker_module.run_worker(("source",))

    assert events == ["close"]


def test_source_generation_real_builders_never_resolve_destination_secret(monkeypatch):
    secret_calls = []

    class SpyResolver:
        def configured(self, reference):
            secret_calls.append(("configured", reference))
            raise AssertionError("dependency construction must not inspect secrets")

        def resolve(self, reference):
            secret_calls.append(("resolve", reference))
            raise AssertionError("dependency construction must not resolve secrets")

    class FakeOwner:
        def get(self, *args, **kwargs):
            return object()

    monkeypatch.setattr("app.core.secrets.EnvironmentSecretResolver", SpyResolver)

    worker_module._build_source_dependencies(FakeOwner())
    worker_module._build_generation_dependencies(FakeOwner())

    assert secret_calls == []
