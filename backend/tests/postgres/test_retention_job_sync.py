from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.jobs.repository import JobRepository
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus
from app.retention.models import RETENTION_SCHEMA_REVISION, RetentionRun
from app.retention.service import (
    RETENTION_CONFIRMATION,
    RetentionService,
)

NOW = datetime(2026, 7, 13, 16, tzinfo=UTC)


async def _linked_run(
    repository: JobRepository,
    db_session,
    *,
    run_status: str = "queued",
) -> tuple[object, RetentionRun]:
    result = await repository.enqueue_job(
        job_type="execute_retention",
        payload={"run_id": "server-owned", "preview_token": "a" * 64},
        idempotency_key=f"retention-sync:{run_status}",
        origin=JobOrigin.MANUAL,
        scheduled_for=NOW - timedelta(minutes=4),
        max_attempts=1,
    )
    run = RetentionRun(
        workflow_job_id=result.job.id,
        status=run_status,
        preview_token=("b" if run_status == "queued" else "c") * 64,
        schema_revision=RETENTION_SCHEMA_REVISION,
        policy_snapshot={},
        candidate_snapshot=[],
        cleanup_intent_snapshot=[],
        count_snapshot={},
        error_snapshot=[],
        previewed_at=NOW - timedelta(minutes=5),
        preview_expires_at=NOW + timedelta(minutes=25),
        queued_at=NOW - timedelta(minutes=4),
        started_at=NOW - timedelta(minutes=3) if run_status == "running" else None,
    )
    db_session.add(run)
    await db_session.flush()
    return result.job, run


async def test_cancelling_retention_job_marks_unstarted_audit_run_failed(
    job_repository,
    db_session,
):
    job, run = await _linked_run(job_repository, db_session)

    await job_repository.cancel_job(job_id=job.id, now=NOW)

    assert run.status == "failed"
    assert run.finished_at == NOW
    assert run.error_snapshot == [
        {
            "phase": "workflow",
            "code": "retention_job_cancelled",
            "message": "Retention workflow job was cancelled before completion",
        }
    ]


async def test_terminal_failure_and_retry_keep_unstarted_retention_run_in_sync(
    job_repository,
    db_session,
):
    job, run = await _linked_run(job_repository, db_session)
    await job_repository.claim_next_job(
        worker_id="worker-retention",
        lease_seconds=60,
        allowed_job_types=("execute_retention",),
        now=NOW - timedelta(seconds=1),
    )

    await job_repository.fail_job(
        job_id=job.id,
        worker_id="worker-retention",
        error_class=JobErrorClass.PERMANENT,
        error_code="retention_conflict",
        error_message="fixed safe failure",
        now=NOW,
    )

    assert job.status == JobStatus.FAILED
    assert run.status == "failed"
    assert run.finished_at == NOW
    assert run.error_snapshot[0]["code"] == "retention_job_failed"

    await job_repository.retry_job(job_id=job.id, now=NOW + timedelta(minutes=1))

    assert run.status == "queued"
    assert run.finished_at is None
    assert run.error_snapshot == []


async def test_terminal_failure_preserves_committed_db_phase_as_partial(
    job_repository,
    db_session,
):
    job, run = await _linked_run(
        job_repository,
        db_session,
        run_status="running",
    )
    await job_repository.claim_next_job(
        worker_id="worker-retention",
        lease_seconds=60,
        allowed_job_types=("execute_retention",),
        now=NOW - timedelta(seconds=1),
    )

    await job_repository.fail_job(
        job_id=job.id,
        worker_id="worker-retention",
        error_class=JobErrorClass.PERMANENT,
        error_code="cleanup_failed",
        error_message="fixed safe failure",
        now=NOW,
    )

    assert run.status == "partial"
    assert run.finished_at == NOW
    assert run.error_snapshot[0]["code"] == "retention_job_failed"


async def test_exact_reconfirmation_revives_the_same_cancelled_retention_job(
    job_repository,
    db_session,
    tmp_path,
):
    service = RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    )
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    await job_repository.cancel_job(job_id=enqueued.job.id, now=NOW)

    revived = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )

    assert revived.created is False
    assert revived.job.id == enqueued.job.id
    assert revived.job.status == JobStatus.QUEUED
    assert revived.run.status == "queued"
    assert revived.run.finished_at is None
    assert revived.run.error_snapshot == []


async def test_exact_reconfirmation_revives_cancelled_partial_cleanup(
    job_repository,
    db_session,
    tmp_path,
):
    service = RetentionService(
        db_session,
        clock=lambda: NOW,
        media_root=tmp_path / "media",
    )
    preview = await service.preview()
    enqueued = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )
    enqueued.run.status = "partial"
    enqueued.run.started_at = NOW - timedelta(minutes=1)
    enqueued.run.finished_at = NOW
    await db_session.flush()
    await job_repository.cancel_job(job_id=enqueued.job.id, now=NOW)

    revived = await service.enqueue(
        preview_token=preview.preview_token,
        confirmation=RETENTION_CONFIRMATION,
    )

    assert revived.job.status == JobStatus.QUEUED
    assert revived.run.status == "partial"
    assert revived.run.started_at == NOW - timedelta(minutes=1)
    assert revived.run.error_snapshot == []
