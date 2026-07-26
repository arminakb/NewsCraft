from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Source
from app.jobs.models import WorkflowEvent, WorkflowJob, WorkflowSchedule
from app.jobs.repository import JobRepository
from app.jobs.scheduler import SchedulerService
from app.jobs.types import JobOrigin, JobStatus

NOW = datetime(2026, 7, 12, 8, 0, tzinfo=UTC)


async def test_expired_lease_is_recovered_by_a_second_worker_with_one_job_history(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        enqueued = await JobRepository(session).enqueue_job(
            job_type="ingest.collect",
            payload={"source_ids": [], "platforms": None},
            idempotency_key="crash-recovery:one",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=NOW,
            pause_sensitive=True,
        )
        job_id = enqueued.job.id
        await session.commit()

    async with session_factory() as session:
        claimed = await JobRepository(session).claim_next_job(
            worker_id="worker-before-crash",
            lease_seconds=1,
            now=NOW,
        )
        assert claimed is not None
        assert claimed.id == job_id
        await session.commit()

    recovered_at = NOW + timedelta(seconds=2)
    async with session_factory() as session:
        recovered = await JobRepository(session).requeue_expired_leases(now=recovered_at)
        assert recovered == 1
        await session.commit()

    async with session_factory() as session:
        claimed = await JobRepository(session).claim_next_job(
            worker_id="worker-after-crash",
            lease_seconds=10,
            now=recovered_at,
        )
        assert claimed is not None
        assert claimed.id == job_id
        await session.commit()

    async with session_factory() as session:
        finished = await JobRepository(session).finish_job(
            job_id=job_id,
            worker_id="worker-after-crash",
            result={"recovered": True},
            now=recovered_at + timedelta(seconds=1),
        )
        assert finished.status == JobStatus.SUCCEEDED
        await session.commit()

    async with session_factory() as session:
        jobs = list(await session.scalars(select(WorkflowJob)))
        events = list(
            await session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_job_id == job_id)
                .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
            )
        )

    assert len(jobs) == 1
    assert jobs[0].id == job_id
    assert jobs[0].status == JobStatus.SUCCEEDED
    assert events == [
        "job.enqueued",
        "job.claimed",
        "job.lease_expired",
        "job.claimed",
        "job.succeeded",
    ]


async def test_scheduler_double_tick_materializes_one_job_for_one_due_source(
    session_factory: async_sessionmaker[AsyncSession],
):
    async with session_factory() as session:
        source = Source(
            platform="rss",
            name="Release 1 scheduler source",
            feed_url="https://example.com/release-1.xml",
            source_group="release-1-test",
            fetch_interval_minutes=30,
            active=True,
        )
        session.add(source)
        await session.commit()
        source_id = source.id

    async with session_factory() as session:
        await SchedulerService(session).tick(NOW)

    due_at = NOW + timedelta(minutes=1)
    async with session_factory() as session:
        schedule = await session.scalar(select(WorkflowSchedule).where(WorkflowSchedule.source_id == source_id))
        assert schedule is not None
        schedule_id = schedule.id
        schedule.next_run_at = due_at
        await session.commit()

    tick_results = []
    for _ in range(2):
        async with session_factory() as session:
            tick_results.append(await SchedulerService(session).tick(due_at))

    async with session_factory() as session:
        jobs = list(await session.scalars(select(WorkflowJob).where(WorkflowJob.job_type == "ingest.collect")))

    assert [result.enqueued for result in tick_results] == [1, 0]
    assert len(jobs) == 1
    assert jobs[0].payload == {"source_ids": [str(source_id)], "platforms": None}
    assert jobs[0].idempotency_key == f"schedule:{schedule_id}:{due_at.isoformat()}"
