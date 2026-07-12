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

from app.jobs.models import RuntimeHeartbeat
from app.jobs.runtime import RuntimeHeartbeatService, build_component_id

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
