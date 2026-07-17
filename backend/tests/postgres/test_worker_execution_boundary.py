from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.faults import InjectedFault, ScriptedFaultInjector
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobHandlerRegistry
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, JobStatus
from app.jobs.worker import WorkerRunner

NOW = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)


async def _enqueue(session_factory: async_sessionmaker[AsyncSession], *, job_type: str) -> object:
    async with session_factory() as session:
        enqueued = await JobRepository(session).enqueue_job(
            job_type=job_type,
            payload={"case": job_type},
            idempotency_key=f"worker-boundary:{job_type}",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=NOW,
        )
        job_id = enqueued.job.id
        await session.commit()
    return job_id


def _runner(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    job_type: str,
    handler,
) -> WorkerRunner:
    registry = JobHandlerRegistry()
    registry.register(job_type, handler)
    return WorkerRunner(
        session_factory=session_factory,
        handler_registry=registry,
        worker_id="worker-boundary",
        capabilities=(),
        clock=lambda: NOW,
        lease_seconds=120,
        heartbeat_seconds=3600,
    )


async def test_committed_handler_side_effect_and_expire_all_still_finish_job(
    session_factory: async_sessionmaker[AsyncSession],
):
    job_type = "boundary.commit-expire"
    job_id = await _enqueue(session_factory, job_type=job_type)

    async def handler(execution: JobExecution, context):
        assert execution.id == job_id
        context.session.add(
            WorkflowEvent(
                workflow_job_id=execution.id,
                event_type="boundary.side_effect_committed",
                actor="test",
                event_data={"durable": True},
            )
        )
        await context.session.commit()
        context.session.expire_all()
        return {"side_effect": "committed"}

    assert await _runner(session_factory, job_type=job_type, handler=handler).run_once() is True

    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        event_types = list(
            await session.scalars(
                select(WorkflowEvent.event_type)
                .where(WorkflowEvent.workflow_job_id == job_id)
                .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
            )
        )
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert job.result == {"side_effect": "committed"}
    assert "boundary.side_effect_committed" in event_types
    assert event_types[-1] == "job.succeeded"


async def test_handler_rollback_and_expire_all_do_not_roll_back_terminal_transition(
    session_factory: async_sessionmaker[AsyncSession],
):
    job_type = "boundary.rollback-expire"
    job_id = await _enqueue(session_factory, job_type=job_type)

    async def handler(execution: JobExecution, context):
        context.session.add(
            WorkflowEvent(
                workflow_job_id=execution.id,
                event_type="boundary.side_effect_rolled_back",
                actor="test",
                event_data={},
            )
        )
        await context.session.flush()
        await context.session.rollback()
        context.session.expire_all()
        return {"side_effect": "rolled_back"}

    assert await _runner(session_factory, job_type=job_type, handler=handler).run_once() is True

    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        rolled_back = await session.scalar(
            select(WorkflowEvent.id).where(
                WorkflowEvent.workflow_job_id == job_id,
                WorkflowEvent.event_type == "boundary.side_effect_rolled_back",
            )
        )
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert job.result == {"side_effect": "rolled_back"}
    assert rolled_back is None


async def test_failed_handler_transaction_isolated_from_retry_transition(
    session_factory: async_sessionmaker[AsyncSession],
):
    job_type = "boundary.failed-transaction"
    job_id = await _enqueue(session_factory, job_type=job_type)

    async def handler(execution: JobExecution, context):
        context.session.add(
            WorkflowEvent(
                workflow_job_id=execution.id,
                event_type=None,
                actor="test",
                event_data={},
            )
        )
        await context.session.flush()
        return {"unreachable": True}

    assert await _runner(session_factory, job_type=job_type, handler=handler).run_once() is True

    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert job.error_code == "unhandled_exception"
    assert job.lease_owner is None


async def test_crash_after_handler_commit_requeues_and_replays_side_effect_once(
    session_factory: async_sessionmaker[AsyncSession],
):
    job_type = "boundary.after-handler-commit"
    job_id = await _enqueue(session_factory, job_type=job_type)
    side_effect_type = "boundary.idempotent_side_effect"

    async def idempotent_handler(execution: JobExecution, context):
        existing = await context.session.scalar(
            select(WorkflowEvent.id).where(
                WorkflowEvent.workflow_job_id == execution.id,
                WorkflowEvent.event_type == side_effect_type,
            )
        )
        if existing is None:
            context.session.add(
                WorkflowEvent(
                    workflow_job_id=execution.id,
                    event_type=side_effect_type,
                    actor="test",
                    event_data={"idempotency_key": str(execution.id)},
                )
            )
        return {"deduplicated": existing is not None}

    crashing_registry = JobHandlerRegistry()
    crashing_registry.register(job_type, idempotent_handler)
    crashing_worker = WorkerRunner(
        session_factory=session_factory,
        handler_registry=crashing_registry,
        worker_id="worker-before-boundary-crash",
        capabilities=(),
        clock=lambda: NOW,
        lease_seconds=120,
        heartbeat_seconds=3600,
        fault_injector=ScriptedFaultInjector({"worker.after_handler_before_terminal": 1}),
    )

    with pytest.raises(InjectedFault, match="worker.after_handler_before_terminal"):
        await crashing_worker.run_once()

    async with session_factory() as session:
        crashed_job = await session.get(WorkflowJob, job_id)
        side_effects = list(
            await session.scalars(
                select(WorkflowEvent.id).where(
                    WorkflowEvent.workflow_job_id == job_id,
                    WorkflowEvent.event_type == side_effect_type,
                )
            )
        )
    assert crashed_job is not None and crashed_job.status == JobStatus.RUNNING
    assert len(side_effects) == 1

    recovered_at = NOW + timedelta(seconds=121)
    async with session_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=recovered_at) == 1
        await session.commit()

    healthy_registry = JobHandlerRegistry()
    healthy_registry.register(job_type, idempotent_handler)
    healthy_worker = WorkerRunner(
        session_factory=session_factory,
        handler_registry=healthy_registry,
        worker_id="worker-after-boundary-crash",
        capabilities=(),
        clock=lambda: recovered_at,
        lease_seconds=120,
        heartbeat_seconds=3600,
    )

    assert await healthy_worker.run_once() is True
    async with session_factory() as session:
        recovered_job = await session.get(WorkflowJob, job_id)
        side_effects = list(
            await session.scalars(
                select(WorkflowEvent.id).where(
                    WorkflowEvent.workflow_job_id == job_id,
                    WorkflowEvent.event_type == side_effect_type,
                )
            )
        )
    assert recovered_job is not None and recovered_job.status == JobStatus.SUCCEEDED
    assert recovered_job.attempt_count == 2
    assert recovered_job.result == {"deduplicated": True}
    assert len(side_effects) == 1


async def test_crash_after_terminal_commit_never_replays_handler(
    session_factory: async_sessionmaker[AsyncSession],
):
    job_type = "boundary.after-terminal-commit"
    job_id = await _enqueue(session_factory, job_type=job_type)
    side_effect_type = "boundary.terminal_side_effect"
    handler_calls = 0

    async def handler(execution: JobExecution, context):
        nonlocal handler_calls
        handler_calls += 1
        context.session.add(
            WorkflowEvent(
                workflow_job_id=execution.id,
                event_type=side_effect_type,
                actor="test",
                event_data={},
            )
        )
        return {"committed": True}

    registry = JobHandlerRegistry()
    registry.register(job_type, handler)
    crashing_worker = WorkerRunner(
        session_factory=session_factory,
        handler_registry=registry,
        worker_id="worker-after-terminal",
        capabilities=(),
        clock=lambda: NOW,
        lease_seconds=120,
        heartbeat_seconds=3600,
        fault_injector=ScriptedFaultInjector({"worker.after_terminal_commit": 1}),
    )

    with pytest.raises(InjectedFault, match="worker.after_terminal_commit"):
        await crashing_worker.run_once()

    healthy_worker = WorkerRunner(
        session_factory=session_factory,
        handler_registry=registry,
        worker_id="worker-after-restart",
        capabilities=(),
        clock=lambda: NOW + timedelta(seconds=1),
        lease_seconds=120,
        heartbeat_seconds=3600,
    )
    assert await healthy_worker.run_once() is False

    async with session_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        side_effects = list(
            await session.scalars(
                select(WorkflowEvent.id).where(
                    WorkflowEvent.workflow_job_id == job_id,
                    WorkflowEvent.event_type == side_effect_type,
                )
            )
        )
    assert job is not None and job.status == JobStatus.SUCCEEDED
    assert job.result == {"committed": True}
    assert handler_calls == 1
    assert len(side_effects) == 1
