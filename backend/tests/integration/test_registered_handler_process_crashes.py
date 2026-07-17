from __future__ import annotations

import asyncio
import multiprocessing
import os
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandlerRegistry, build_default_registry
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, JobStatus
from app.jobs.worker import WorkerRunner

CRASH_EXIT_CODE = 86
CHILD_ERROR_EXIT_CODE = 87
LEASE_SECONDS = 2
STARTED_AT = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)
SIDE_EFFECT_EVENT = "phase2.process_crash_side_effect"

REGISTERED_JOB_TYPES = (
    "ingest.collect",
    "manual_intake",
    "story.group_pending",
    "telegram.route.backfill",
    "telegram.route.dry_run",
    "telegram.route.initialize",
    "telegram.route.poll",
    "telegram.route.process",
    "content_pack.generate",
    "content_pack.generate_telegram",
    "content_pack.regenerate",
    "build_export",
    "execute_retention",
    "research_story",
    "telegram.destination.check",
    "telegram.publish",
)


class ProcessExitFaultInjector:
    """Terminate the interpreter at one production fault point.

    This intentionally uses ``os._exit``: no Python exception, ``finally`` block,
    task cancellation, SQLAlchemy cleanup, or pytest unwinding runs in the child.
    """

    def __init__(self, target: str) -> None:
        self.target = target

    async def hit(self, point: str, context) -> None:
        if point == self.target:
            os._exit(CRASH_EXIT_CODE)


async def _idempotent_probe_handler(execution: JobExecution, context: JobContext) -> dict[str, bool]:
    existing = await context.session.scalar(
        select(WorkflowEvent.id).where(
            WorkflowEvent.workflow_job_id == execution.id,
            WorkflowEvent.event_type == SIDE_EFFECT_EVENT,
        )
    )
    if existing is None:
        context.session.add(
            WorkflowEvent(
                workflow_job_id=execution.id,
                event_type=SIDE_EFFECT_EVENT,
                actor="phase2-process-test",
                event_data={"idempotency_key": str(execution.id)},
            )
        )
    return {"deduplicated": existing is not None}


async def _run_probe_worker(
    database_url: str,
    job_type: str,
    fault_point: str | None,
    observed_at: str,
) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = JobHandlerRegistry()
    registry.register(job_type, _idempotent_probe_handler)
    runner = WorkerRunner(
        session_factory=factory,
        handler_registry=registry,
        worker_id=f"process-crash:{job_type}:{fault_point or 'healthy'}",
        capabilities=(),
        clock=lambda: datetime.fromisoformat(observed_at),
        lease_seconds=LEASE_SECONDS,
        heartbeat_seconds=3600,
        fault_injector=(ProcessExitFaultInjector(fault_point) if fault_point is not None else None),
    )
    try:
        await runner.run_once()
    finally:
        await runner.close()
        await engine.dispose()


def _probe_worker_process(
    database_url: str,
    job_type: str,
    fault_point: str | None,
    observed_at: str,
    error_path: str,
) -> None:
    try:
        asyncio.run(_run_probe_worker(database_url, job_type, fault_point, observed_at))
    except BaseException:  # pragma: no cover - reported in the parent with the child traceback
        Path(error_path).write_text(traceback.format_exc(), encoding="utf-8")
        os._exit(CHILD_ERROR_EXIT_CODE)


def _run_child(
    *,
    database_url: str,
    job_type: str,
    fault_point: str | None,
    observed_at: datetime,
    error_path: Path,
    expected_exit_code: int,
) -> None:
    process = multiprocessing.get_context("spawn").Process(
        target=_probe_worker_process,
        args=(database_url, job_type, fault_point, observed_at.isoformat(), str(error_path)),
    )
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        pytest.fail(f"child worker hung for {job_type} at {fault_point}")
    child_error = error_path.read_text(encoding="utf-8") if error_path.exists() else ""
    assert process.exitcode == expected_exit_code, child_error


async def _recover_expired_lease(release3_factory, *, observed_at: datetime) -> None:
    async with release3_factory() as session:
        assert await JobRepository(session).requeue_expired_leases(now=observed_at) == 1
        await session.commit()


async def _job_state(release3_factory, job_id):
    async with release3_factory() as session:
        job = await session.get(WorkflowJob, job_id)
        effects = list(
            await session.scalars(
                select(WorkflowEvent.id).where(
                    WorkflowEvent.workflow_job_id == job_id,
                    WorkflowEvent.event_type == SIDE_EFFECT_EVENT,
                )
            )
        )
        assert job is not None
        return job.status, job.attempt_count, job.result, len(effects)


def test_literal_process_matrix_matches_all_default_registry_keys(tmp_path: Path):
    registry = build_default_registry(
        capabilities=("ingestion", "source", "generation", "publishing"),
        source_registry=object(),
        media_stager=object(),
        profile_resolver=object(),
        research_backend_resolver=object(),
        export_root=tmp_path / "exports",
        media_root=tmp_path / "media",
        telegram_client=object(),
        destination_secret_resolver=object(),
    )

    assert len(REGISTERED_JOB_TYPES) == 16
    assert set(REGISTERED_JOB_TYPES) == set(registry.job_types())


@pytest.mark.parametrize("job_type", REGISTERED_JOB_TYPES)
async def test_registered_job_recovers_from_literal_process_death_without_duplicate_effect(
    release3_factory,
    tmp_path: Path,
    job_type: str,
):
    """Exercise the common execution contract for every production registry key.

    Handler-specific suites separately prove each production idempotency mechanism.
    This matrix proves that each exact registered job type survives literal worker
    death before an effect, after a committed effect, and after terminal commit.
    """

    database_url = os.environ["TEST_DATABASE_URL"]
    async with release3_factory() as session:
        enqueued = await JobRepository(session).enqueue_job(
            job_type=job_type,
            payload={"phase2_process_test": True},
            idempotency_key=f"phase2-process:{job_type}",
            origin=JobOrigin.AUTOMATION,
            scheduled_for=STARTED_AT,
            max_attempts=3,
        )
        job_id = enqueued.job.id
        await session.commit()

    # Crash after claim: the handler and its material effect never run.
    _run_child(
        database_url=database_url,
        job_type=job_type,
        fault_point="worker.after_claim",
        observed_at=STARTED_AT,
        error_path=tmp_path / "after-claim.txt",
        expected_exit_code=CRASH_EXIT_CODE,
    )
    assert await _job_state(release3_factory, job_id) == (JobStatus.RUNNING, 1, {}, 0)

    second_claim_at = STARTED_AT + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover_expired_lease(release3_factory, observed_at=second_claim_at)

    # Crash after the handler transaction commits but before job completion.
    _run_child(
        database_url=database_url,
        job_type=job_type,
        fault_point="worker.after_handler_before_terminal",
        observed_at=second_claim_at,
        error_path=tmp_path / "after-handler.txt",
        expected_exit_code=CRASH_EXIT_CODE,
    )
    assert await _job_state(release3_factory, job_id) == (JobStatus.RUNNING, 2, {}, 1)

    third_claim_at = second_claim_at + timedelta(seconds=LEASE_SECONDS + 1)
    await _recover_expired_lease(release3_factory, observed_at=third_claim_at)

    # The replay deduplicates the effect, commits success, then the process dies.
    _run_child(
        database_url=database_url,
        job_type=job_type,
        fault_point="worker.after_terminal_commit",
        observed_at=third_claim_at,
        error_path=tmp_path / "after-terminal.txt",
        expected_exit_code=CRASH_EXIT_CODE,
    )
    assert await _job_state(release3_factory, job_id) == (
        JobStatus.SUCCEEDED,
        3,
        {"deduplicated": True},
        1,
    )

    # A restarted healthy worker has no claim and cannot replay the side effect.
    _run_child(
        database_url=database_url,
        job_type=job_type,
        fault_point=None,
        observed_at=third_claim_at + timedelta(seconds=1),
        error_path=tmp_path / "healthy-restart.txt",
        expected_exit_code=0,
    )
    assert await _job_state(release3_factory, job_id) == (
        JobStatus.SUCCEEDED,
        3,
        {"deduplicated": True},
        1,
    )
