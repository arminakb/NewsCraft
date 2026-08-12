from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestRun, Source
from app.db.session import get_session
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.handlers import handle_source_collection_continuous_cycle
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.scheduler import SchedulerService, build_due_continuous_subscription_statement
from app.jobs.types import JobExecution
from app.main import app
from app.source_collections.continuous import (
    ContinuousSubscriptionConflict,
    start_subscription,
    stop_subscription,
)
from app.source_collections.models import IngestRunSourceSnapshot, SourceCollectionMembership
from app.source_collections.repository import create_collection

NOW = datetime(2026, 8, 7, 8, 0, tzinfo=UTC)


async def _request(session: AsyncSession, method: str, path: str, **kwargs):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_session, None)


async def _create_source(session: AsyncSession, name: str) -> Source:
    source = Source(
        id=uuid4(),
        platform="rss",
        name=name,
        feed_url=f"https://example.com/{uuid4()}.xml",
        source_group="test",
    )
    session.add(source)
    await session.flush()
    return source


async def _create_collection_with_sources(
    session: AsyncSession,
    name: str,
    source_count: int = 0,
):
    collection = await create_collection(session, name=name, description=None)
    sources = [await _create_source(session, f"{name} source {index}") for index in range(source_count)]
    session.add_all(
        [
            SourceCollectionMembership(collection_id=collection.id, source_id=source.id)
            for source in sources
        ]
    )
    await session.commit()
    return collection, sources


async def _claim_continuous_cycle(session: AsyncSession, *, now: datetime) -> JobExecution:
    repository = JobRepository(session)
    job = await session.scalar(
        select(WorkflowJob)
        .where(WorkflowJob.job_type == "ingest.collection.continuous_cycle")
        .order_by(WorkflowJob.created_at.desc())
    )
    assert job is not None
    claimed = await repository.claim_next_job(worker_id="continuous-test-worker", lease_seconds=120, now=now)
    assert claimed is not None
    assert claimed.id == job.id
    await session.commit()
    return JobExecution.from_job(claimed)


async def test_empty_collection_subscription_is_durable_and_idempotent(db_session: AsyncSession):
    collection, _ = await _create_collection_with_sources(db_session, "Empty continuous")
    collection_id = collection.id

    first, deduplicated = await start_subscription(
        db_session,
        collection_id=collection.id,
        idempotency_key="continuous-empty-1",
        interval_minutes=5,
        now=NOW,
    )
    assert deduplicated is False
    assert first.status == "starting"
    assert first.source_collection_id == collection.id
    assert first.next_cycle_at == NOW
    assert first.interval_minutes == 5
    subscription_id = first.id
    await db_session.commit()

    repeated, deduplicated = await start_subscription(
        db_session,
        collection_id=collection.id,
        idempotency_key="continuous-empty-1",
        interval_minutes=5,
        now=NOW,
    )
    assert deduplicated is True
    assert repeated.id == first.id
    await db_session.rollback()

    with pytest.raises(ContinuousSubscriptionConflict) as conflict:
        await start_subscription(
            db_session,
            collection_id=collection_id,
            idempotency_key="continuous-empty-2",
            now=NOW,
        )
    assert conflict.value.code == "continuous_ingestion_already_running"
    await db_session.rollback()

    stopped = await stop_subscription(db_session, subscription_id, now=NOW + timedelta(minutes=1))
    await db_session.commit()
    assert stopped.status == "stopped"
    assert stopped.next_cycle_at is None

    resumed, deduplicated = await start_subscription(
        db_session,
        collection_id=collection_id,
        idempotency_key="continuous-empty-3",
        now=NOW + timedelta(minutes=2),
    )
    assert deduplicated is False
    assert resumed.id != subscription_id
    assert resumed.cycle_count == 0


async def test_empty_continuous_cycle_waits_without_creating_ingest_run(db_session: AsyncSession):
    collection, _ = await _create_collection_with_sources(db_session, "Empty cycle")
    subscription, _ = await start_subscription(
        db_session,
        collection_id=collection.id,
        idempotency_key="continuous-empty-cycle-1",
        interval_minutes=5,
        now=NOW,
    )
    await db_session.commit()

    scheduler = SchedulerService(db_session)
    await scheduler.tick(NOW)
    execution = await _claim_continuous_cycle(db_session, now=datetime.now(UTC))
    result = await handle_source_collection_continuous_cycle(
        execution,
        JobContext(session=db_session, providers=build_default_provider_registry()),
    )
    await db_session.commit()

    assert result["status"] == "waiting_for_sources"
    refreshed = await db_session.get(type(subscription), subscription.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert refreshed.last_cycle_status == "waiting_for_sources"
    assert refreshed.cycle_count == 1
    assert refreshed.current_cycle_job_id is None
    assert refreshed.next_cycle_at is not None
    assert await db_session.scalar(
        select(IngestRun.id).where(IngestRun.continuous_subscription_id == subscription.id)
    ) is None


async def test_source_collection_api_exposes_mode_status_stop_and_persistence(db_session: AsyncSession):
    created = await _request(
        db_session,
        "POST",
        "/source-collections",
        json={"name": "API continuous", "description": "  "},
    )
    assert created.status_code == 201, created.text
    collection = created.json()
    assert collection["source_count"] == 0
    assert collection["description"] is None

    invalid = await _request(
        db_session,
        "POST",
        "/source-collections",
        json={"name": "Rejected fields", "source_ids": []},
    )
    assert invalid.status_code == 422

    started = await _request(
        db_session,
        "POST",
        f"/source-collections/{collection['id']}/ingest",
        json={"mode": "continuous", "request_id": str(uuid4())},
    )
    assert started.status_code == 202, started.text
    accepted = started.json()
    assert accepted["mode"] == "continuous"
    assert accepted["source_count"] == 0
    assert accepted["subscription_id"]

    refreshed = await _request(db_session, "GET", f"/source-collections/{collection['id']}")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["source_count"] == 0
    assert refreshed.json()["continuous_status"] == "starting"

    status = await _request(db_session, "GET", f"/source-collections/{collection['id']}/continuous")
    assert status.status_code == 200, status.text
    assert status.json()["id"] == accepted["subscription_id"]

    once_while_continuous = await _request(
        db_session,
        "POST",
        f"/source-collections/{collection['id']}/ingest",
        json={"mode": "once", "request_id": str(uuid4())},
    )
    assert once_while_continuous.status_code == 409
    assert once_while_continuous.json()["detail"]["code"] == "continuous_ingestion_already_running"

    stopped = await _request(db_session, "POST", f"/source-collections/{collection['id']}/continuous/stop")
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "stopped"

    duplicate = await _request(db_session, "POST", "/source-collections", json={"name": " API continuous "})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["message"] == "source collection name already exists"


async def test_scheduler_materializes_one_cycle_and_does_not_overlap(db_session: AsyncSession):
    collection, _ = await _create_collection_with_sources(db_session, "Scheduler continuous")
    subscription, _ = await start_subscription(
        db_session,
        collection_id=collection.id,
        idempotency_key="continuous-scheduler-1",
        now=NOW,
    )
    await db_session.commit()

    scheduler = SchedulerService(db_session)
    first = await scheduler.tick(NOW)
    second = await scheduler.tick(NOW)

    assert first.continuous_enqueued == 1
    assert second.continuous_enqueued == 0
    jobs = list(
        await db_session.scalars(
            select(WorkflowJob).where(WorkflowJob.job_type == "ingest.collection.continuous_cycle")
        )
    )
    assert len(jobs) == 1
    assert jobs[0].payload == {"subscription_id": str(subscription.id), "cycle_number": 1}
    refreshed = await db_session.get(type(subscription), subscription.id)
    assert refreshed is not None
    assert refreshed.status == "running"
    assert refreshed.current_cycle_job_id == jobs[0].id
    jobs[0].status = "succeeded"
    jobs[0].result = {"status": "succeeded", "cycle_number": 1}
    await db_session.commit()
    recovered = await scheduler.tick(NOW + timedelta(minutes=1))
    assert recovered.continuous_enqueued == 0
    recovered_subscription = await db_session.get(type(subscription), subscription.id)
    assert recovered_subscription is not None
    assert recovered_subscription.cycle_count == 1
    assert recovered_subscription.current_cycle_job_id is None
    assert recovered_subscription.next_cycle_at > NOW + timedelta(minutes=1)
    await db_session.rollback()

    sql = str(build_due_continuous_subscription_statement(NOW).compile(dialect=db_session.bind.dialect))
    assert "FOR UPDATE SKIP LOCKED" in sql


@pytest.mark.asyncio
async def test_continuous_cycles_use_fresh_membership_snapshots(monkeypatch, db_session: AsyncSession):
    collection, sources = await _create_collection_with_sources(db_session, "Fresh snapshots", source_count=1)
    subscription, _ = await start_subscription(
        db_session,
        collection_id=collection.id,
        idempotency_key="continuous-snapshot-1",
        interval_minutes=1,
        now=NOW,
    )
    await db_session.commit()

    async def fake_ingest(job, context, payload):
        run = await context.session.get(IngestRun, UUID(payload["ingest_run_id"]))
        assert run is not None
        run.status = "succeeded"
        run.finished_at = NOW
        run.processed_count = run.source_count
        run.success_count = run.source_count
        run.stats = {"checked": run.source_count, "failed": 0, "items": 1}
        return run.stats

    monkeypatch.setattr("app.jobs.handlers._handle_ingest_collect_payload", fake_ingest)
    scheduler = SchedulerService(db_session)
    await scheduler.tick(NOW)
    execution = await _claim_continuous_cycle(db_session, now=datetime.now(UTC))
    first_result = await handle_source_collection_continuous_cycle(
        execution,
        JobContext(session=db_session, providers=build_default_provider_registry()),
    )
    await db_session.commit()
    assert first_result["status"] == "succeeded"

    added = await _create_source(db_session, "Fresh snapshots source 2")
    db_session.add(SourceCollectionMembership(collection_id=collection.id, source_id=added.id))
    await db_session.commit()

    subscription = await db_session.get(type(subscription), subscription.id)
    assert subscription is not None
    subscription.next_cycle_at = NOW
    await db_session.commit()
    await scheduler.tick(NOW + timedelta(minutes=2))
    second_execution = await _claim_continuous_cycle(db_session, now=datetime.now(UTC))
    second_result = await handle_source_collection_continuous_cycle(
        second_execution,
        JobContext(session=db_session, providers=build_default_provider_registry()),
    )
    await db_session.commit()
    assert second_result["status"] == "succeeded"

    runs = list(
        await db_session.scalars(
            select(IngestRun)
            .where(IngestRun.continuous_subscription_id == subscription.id)
            .order_by(IngestRun.continuous_cycle_number)
        )
    )
    assert [run.continuous_cycle_number for run in runs] == [1, 2]
    assert [run.source_count for run in runs] == [1, 2]
    assert all(run.continuous_subscription_id == subscription.id for run in runs)
    snapshots = list(
        await db_session.scalars(
            select(IngestRunSourceSnapshot)
            .where(IngestRunSourceSnapshot.ingest_run_id == runs[0].id)
        )
    )
    assert [snapshot.source_id for snapshot in snapshots] == [sources[0].id]
