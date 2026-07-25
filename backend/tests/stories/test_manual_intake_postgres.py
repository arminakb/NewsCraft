from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.db.model_registry import Base
from app.db.models import ContentItem, RawPayload, SourceItem
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.errors import RetryableJobError
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus
from app.stories.handlers import handle_manual_intake
from app.stories.models import Story, StoryEvidenceSnapshot

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest_asyncio.fixture(scope="module")
async def manual_engine() -> AsyncIterator[AsyncEngine]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    database_name = make_url(TEST_DATABASE_URL).database
    if not database_name or not database_name.endswith("_test"):
        raise RuntimeError("Refusing destructive PostgreSQL tests unless database ends in '_test'")
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def manual_factory(manual_engine: AsyncEngine):
    table_names = [manual_engine.dialect.identifier_preparer.quote(table.name) for table in Base.metadata.sorted_tables]
    async with manual_engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE"))
    return async_sessionmaker(manual_engine, expire_on_commit=False)


def manual_job() -> WorkflowJob:
    now = datetime.now(UTC)
    return WorkflowJob(
        id=uuid4(),
        job_type="manual_intake",
        status=JobStatus.QUEUED,
        payload={
            "kind": "text",
            "title": "Operator note",
            "text": "Confirmed source material supplied by the operator.",
            "source_label": "Operator interview",
            "source_url": None,
        },
        result={},
        priority=5,
        idempotency_key=f"manual-race:{uuid4()}",
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
        scheduled_for=now,
        attempt_count=0,
        max_attempts=3,
        progress=0,
        created_at=now,
        updated_at=now,
    )


async def count_rows(session: AsyncSession, model, *criteria) -> int:
    statement = select(func.count()).select_from(model)
    for criterion in criteria:
        statement = statement.where(criterion)
    return int(await session.scalar(statement) or 0)


@pytest.mark.asyncio
async def test_two_session_manual_replay_serializes_to_one_complete_materialization(
    manual_factory,
):
    async with manual_factory() as setup:
        job = manual_job()
        setup.add(job)
        await setup.commit()
        job_id = job.id

    ready = asyncio.Event()
    arrivals = 0
    arrivals_lock = asyncio.Lock()

    async def run_handler() -> dict[str, object]:
        nonlocal arrivals
        async with manual_factory() as session:
            replay_job = await session.get(WorkflowJob, job_id)
            async with arrivals_lock:
                arrivals += 1
                if arrivals == 2:
                    ready.set()
            await ready.wait()
            result = await handle_manual_intake(
                replay_job,
                JobContext(session=session, providers=build_default_provider_registry()),
            )
            await session.commit()
            return result

    first, second = await asyncio.gather(run_handler(), run_handler())

    assert first == second
    async with manual_factory() as session:
        assert await count_rows(session, Story) == 1
        assert await count_rows(session, StoryEvidenceSnapshot) == 1
        assert await count_rows(session, RawPayload) == 1
        assert await count_rows(session, ContentItem) == 1
        assert await count_rows(session, SourceItem) == 1
        assert (
            await count_rows(
                session,
                WorkflowEvent,
                WorkflowEvent.workflow_job_id == job_id,
                WorkflowEvent.event_type == "manual_intake.completed",
            )
            == 1
        )


@pytest.mark.asyncio
async def test_late_database_failure_rolls_back_manual_rows_and_keeps_outer_session_usable(
    manual_factory,
):
    async with manual_factory() as setup:
        job = manual_job()
        job.status = JobStatus.RUNNING
        job.attempt_count = 1
        job.lease_owner = "manual-worker"
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        setup.add(job)
        await setup.commit()
        job_id = job.id

    async with manual_factory() as session:
        running_job = await session.get(WorkflowJob, job_id)

        def fail_completion_flush(sync_session, flush_context, instances):
            if any(
                isinstance(value, WorkflowEvent) and value.event_type == "manual_intake.completed"
                for value in sync_session.new
            ):
                raise RuntimeError("forced late persistence failure")

        event.listen(session.sync_session, "before_flush", fail_completion_flush)
        try:
            with pytest.raises(RetryableJobError) as error:
                await handle_manual_intake(
                    running_job,
                    JobContext(session=session, providers=build_default_provider_registry()),
                )
        finally:
            event.remove(session.sync_session, "before_flush", fail_completion_flush)

        assert error.value.code == "manual_intake_persistence_failed"
        assert await count_rows(session, Story) == 0
        assert await count_rows(session, StoryEvidenceSnapshot) == 0
        assert await count_rows(session, RawPayload) == 0
        assert await count_rows(session, ContentItem) == 0
        assert await count_rows(session, SourceItem) == 0
        assert (
            await count_rows(
                session,
                WorkflowEvent,
                WorkflowEvent.event_type == "manual_intake.completed",
            )
            == 0
        )

        failed_job = await JobRepository(session).fail_job(
            job_id=job_id,
            worker_id="manual-worker",
            error_class=JobErrorClass.RETRYABLE,
            error_code=error.value.code,
            error_message=error.value.message,
            now=datetime.now(UTC),
        )
        await session.commit()
        assert failed_job.status == JobStatus.QUEUED
