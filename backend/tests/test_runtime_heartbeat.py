import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.outbound_proxy import ProxyDiagnostics
from app.jobs import scheduler as scheduler_module
from app.jobs.models import RuntimeHeartbeat
from app.jobs.registry import JobHandlerRegistry
from app.jobs.runtime import RuntimeHeartbeatService, build_component_id
from app.jobs.worker import WorkerRunner

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

if TEST_DATABASE_URL:
    database_name = make_url(TEST_DATABASE_URL).database
    if not database_name or not database_name.endswith("_test"):
        raise RuntimeError("Refusing heartbeat acceptance tests unless the database name ends in '_test'")


@pytest_asyncio.fixture
async def heartbeat_db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL heartbeat acceptance tests")
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(RuntimeHeartbeat.__table__.create, checkfirst=True)
        await connection.execute(delete(RuntimeHeartbeat))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
            await session.rollback()
    finally:
        await engine.dispose()


class FakeScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class FakeSession:
    def __init__(self, rows=()):
        self.statements = []
        self.rows = rows

    async def execute(self, statement):
        self.statements.append(statement)

    async def scalars(self, statement):
        self.statements.append(statement)
        return FakeScalarRows(self.rows)


@pytest.mark.asyncio
async def test_runtime_heartbeat_upsert_preserves_supplied_time_capabilities_and_redacts_metadata():
    session = FakeSession()
    source_time = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    service = RuntimeHeartbeatService(session)

    await service.record(
        component_id="worker-source-1",
        component_type="worker",
        capabilities=("source", "ingestion", "source"),
        observed_at=source_time,
        metadata={"pid": 101, "nested": {"api_key": "secret", "safe": "visible"}},
    )

    statement = session.statements[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    params = statement.compile(dialect=postgresql.dialect()).params
    assert "ON CONFLICT (component_id) DO UPDATE" in sql
    assert params["capabilities"] == ["ingestion", "source"]
    assert params["observed_at"] == source_time
    assert params["metadata"]["nested"] == {"api_key": "[REDACTED]", "safe": "visible"}


@pytest.mark.asyncio
async def test_list_recent_orders_all_components_by_observation_time_descending():
    first = object()
    second = object()
    session = FakeSession([first, second])

    rows = await RuntimeHeartbeatService(session).list_recent()

    assert rows == [first, second]
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ORDER BY runtime_heartbeats.observed_at DESC" in sql


@pytest.mark.asyncio
async def test_runtime_heartbeat_rejects_naive_observation_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        await RuntimeHeartbeatService(FakeSession()).record(
            "scheduler-1", "scheduler", ("scheduling",), datetime(2026, 7, 11), {}
        )


def test_component_id_uses_explicit_environment_or_truthful_process_identity(monkeypatch):
    monkeypatch.setenv("NEWSCRAFT_COMPONENT_ID", "worker-source-1")
    assert build_component_id("worker") == "worker-source-1"
    monkeypatch.delenv("NEWSCRAFT_COMPONENT_ID")
    generated = build_component_id("scheduler")
    assert generated.startswith("scheduler:")
    assert generated.count(":") == 2


@pytest.mark.asyncio
async def test_runtime_heartbeats_preserve_each_component_and_supplied_observation_time(
    heartbeat_db_session,
):
    service = RuntimeHeartbeatService(heartbeat_db_session)
    source_time = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    publish_time = datetime(2026, 7, 11, 8, 0, 5, tzinfo=UTC)

    await service.record(
        component_id="worker-source-1",
        component_type="worker",
        capabilities=("ingestion", "source", "generation"),
        observed_at=source_time,
        metadata={"pid": 101},
    )
    await service.record(
        component_id="worker-publish-1",
        component_type="worker",
        capabilities=("publishing",),
        observed_at=publish_time,
        metadata={"pid": 202},
    )

    rows = await service.list_recent()
    assert {row.component_id for row in rows} == {"worker-source-1", "worker-publish-1"}
    assert next(row for row in rows if row.component_id == "worker-source-1").observed_at == source_time


@pytest.mark.asyncio
async def test_repeated_component_heartbeat_updates_in_place(heartbeat_db_session):
    service = RuntimeHeartbeatService(heartbeat_db_session)
    first = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    second = datetime(2026, 7, 11, 8, 0, 5, tzinfo=UTC)
    await service.record("scheduler-1", "scheduler", ("scheduling",), first, {})
    await service.record("scheduler-1", "scheduler", ("scheduling",), second, {"tick": 2})

    rows = await service.list_recent()
    assert len(rows) == 1
    assert rows[0].observed_at == second
    assert rows[0].runtime_metadata == {"tick": 2}


@pytest.mark.asyncio
async def test_process_instance_changes_accumulate_bounded_restart_history(
    heartbeat_db_session,
):
    service = RuntimeHeartbeatService(heartbeat_db_session)
    first = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    second = datetime(2026, 7, 11, 8, 1, tzinfo=UTC)
    third = datetime(2026, 7, 11, 8, 2, tzinfo=UTC)

    await service.record(
        "worker-source-generation",
        "worker",
        ("ingestion",),
        first,
        {
            "process_instance_id": "instance-a",
            "process_started_at": first.isoformat(),
        },
    )
    await heartbeat_db_session.commit()
    await service.record(
        "worker-source-generation",
        "worker",
        ("ingestion",),
        second,
        {
            "process_instance_id": "instance-b",
            "process_started_at": second.isoformat(),
        },
    )
    await heartbeat_db_session.commit()
    await service.record(
        "worker-source-generation",
        "worker",
        ("ingestion",),
        third,
        {
            "process_instance_id": "instance-c",
            "process_started_at": third.isoformat(),
        },
    )
    await heartbeat_db_session.commit()

    row = (await service.list_recent())[0]
    assert row.runtime_metadata["restart_observed_at"] == [
        second.isoformat(),
        third.isoformat(),
    ]


@pytest.mark.asyncio
async def test_two_worker_heartbeats_report_exact_capabilities_registry_jobs_and_supplied_time(monkeypatch):
    records = []
    monkeypatch.setattr(
        "app.jobs.worker.safe_proxy_diagnostics",
        lambda: ProxyDiagnostics(
            mode="direct",
            bypass_rule_count=0,
            last_connectivity_status="not_checked",
        ),
    )
    monkeypatch.setattr(
        "app.jobs.worker.uuid4",
        lambda: type("ProcessInstance", (), {"hex": "process-instance"})(),
    )

    class SessionContext(FakeSession):
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def commit(self):
            return None

    class Recorder:
        def __init__(self, session):
            pass

        async def record(self, **kwargs):
            records.append(kwargs)

    observed_at = datetime(2026, 7, 12, 10, 30, tzinfo=UTC)
    source_registry = JobHandlerRegistry()
    publishing_registry = JobHandlerRegistry()

    async def handler(job, context):
        return {}

    source_registry.register("telegram.route.poll", handler)
    source_registry.register("telegram.route.process", handler)
    publishing_registry.register("telegram.publish", handler)

    for component_id, capabilities, registry in (
        ("worker-source-generation", ("ingestion", "source", "generation"), source_registry),
        ("worker-publishing", ("publishing",), publishing_registry),
    ):
        runner = WorkerRunner(
            session_factory=lambda: SessionContext(),
            handler_registry=registry,
            runtime_service_factory=Recorder,
            worker_id=component_id,
            capabilities=capabilities,
            clock=lambda: observed_at,
        )
        await runner._record_runtime_heartbeat(observed_at)

    assert records == [
        {
            "component_id": "worker-source-generation",
            "component_type": "worker",
            "capabilities": ("generation", "ingestion", "source"),
            "observed_at": observed_at,
            "metadata": {
                "job_types": ["telegram.route.poll", "telegram.route.process"],
                "state": "idle",
                "active_work_type": None,
                "active_work_started_at": None,
                "last_success_at": None,
                "process_instance_id": "process-instance",
                "process_started_at": observed_at.isoformat(),
                "outbound_proxy": {
                    "mode": "direct",
                    "scheme": None,
                    "bypass_rule_count": 0,
                    "last_connectivity_status": "not_checked",
                    "configuration_error_code": None,
                },
            },
        },
        {
            "component_id": "worker-publishing",
            "component_type": "worker",
            "capabilities": ("publishing",),
            "observed_at": observed_at,
            "metadata": {
                "job_types": ["telegram.publish"],
                "state": "idle",
                "active_work_type": None,
                "active_work_started_at": None,
                "last_success_at": None,
                "process_instance_id": "process-instance",
                "process_started_at": observed_at.isoformat(),
                "outbound_proxy": {
                    "mode": "direct",
                    "scheme": None,
                    "bypass_rule_count": 0,
                    "last_connectivity_status": "not_checked",
                    "configuration_error_code": None,
                },
            },
        },
    ]


def test_worker_heartbeat_proxy_projection_never_persists_proxy_credentials(monkeypatch):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "ALL_PROXY",
        "http://heartbeat-user-canary:heartbeat-password-canary@heartbeat-host-canary.example:8080",
    )
    runner = WorkerRunner(
        session_factory=lambda: FakeSession(),
        handler_registry=JobHandlerRegistry(),
        worker_id="worker-source-generation",
        capabilities=("ingestion",),
    )

    metadata = runner._runtime_metadata()

    assert metadata["outbound_proxy"] == {
        "mode": "proxy",
        "scheme": "http",
        "bypass_rule_count": 0,
        "last_connectivity_status": metadata["outbound_proxy"]["last_connectivity_status"],
        "configuration_error_code": None,
    }
    assert "canary" not in repr(metadata)


@pytest.mark.asyncio
async def test_scheduler_heartbeat_has_own_identity_type_and_no_secret_metadata(monkeypatch):
    monkeypatch.setenv("NEWSCRAFT_COMPONENT_ID", "scheduler")
    observed_at = datetime(2026, 7, 12, 10, 31, tzinfo=UTC)
    session = FakeSession()

    await RuntimeHeartbeatService(session).record(
        component_id=build_component_id("scheduler"),
        component_type="scheduler",
        capabilities=("scheduling",),
        observed_at=observed_at,
        metadata={},
    )

    params = session.statements[0].compile(dialect=postgresql.dialect()).params
    assert params["component_id"] == "scheduler"
    assert params["component_type"] == "scheduler"
    assert params["capabilities"] == ["scheduling"]
    assert params["observed_at"] == observed_at
    assert params["metadata"] == {}


@pytest.mark.asyncio
async def test_scheduler_runtime_heartbeat_is_independent_and_allowlisted(monkeypatch):
    records = []

    class SessionContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def commit(self):
            return None

    class Recorder:
        def __init__(self, _session):
            pass

        async def record(self, **kwargs):
            records.append(kwargs)

    monkeypatch.setattr(scheduler_module, "async_session", lambda: SessionContext())
    monkeypatch.setattr(scheduler_module, "RuntimeHeartbeatService", Recorder)
    runtime_state = {
        "state": "ticking",
        "active_work_started_at": "2026-07-17T08:30:00+00:00",
        "last_success_at": "2026-07-17T08:29:45+00:00",
        "last_duration_ms": 12,
        "last_result": {"enqueued": 1},
    }
    stop = asyncio.Event()
    started = asyncio.Event()

    task = asyncio.create_task(
        scheduler_module._scheduler_runtime_heartbeat_loop(
            component_id="scheduler",
            runtime_state=runtime_state,
            stop=stop,
            started=started,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    stop.set()
    await asyncio.wait_for(task, timeout=1)

    assert len(records) == 1
    assert records[0]["component_id"] == "scheduler"
    assert records[0]["component_type"] == "scheduler"
    assert records[0]["capabilities"] == ("scheduling",)
    assert records[0]["metadata"] == runtime_state
