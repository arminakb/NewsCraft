from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.jobs.capability_gate import (
    API_CAPABILITY_GATE_SESSION_KEY,
    API_CAPABILITY_GATE_SNAPSHOT_KEY,
    require_available_job_type,
)
from app.jobs.errors import JobCapabilityUnavailable
from app.jobs.models import RuntimeHeartbeat, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin, JobStatus


def _heartbeat(observed_at: datetime, *, job_types: list[str]) -> RuntimeHeartbeat:
    return RuntimeHeartbeat(
        component_id=f"worker-{uuid4()}",
        component_type="worker",
        capabilities=["ingestion"],
        observed_at=observed_at,
        runtime_metadata={
            "job_types": job_types,
            "state": "idle",
            "last_success_at": observed_at.isoformat(),
        },
    )


@pytest.mark.asyncio
async def test_api_gate_accepts_only_a_fresh_exact_job_type(db_session):
    observed_at = datetime.now(UTC)
    db_session.info[API_CAPABILITY_GATE_SESSION_KEY] = True
    db_session.add(_heartbeat(observed_at, job_types=["manual_intake"]))
    await db_session.flush()

    await require_available_job_type(db_session, "manual_intake")
    with pytest.raises(JobCapabilityUnavailable) as wrong:
        await require_available_job_type(db_session, "ingest.collect")
    assert wrong.value.code == "job_capability_unavailable"

    heartbeat = await db_session.scalar(select(RuntimeHeartbeat))
    heartbeat.observed_at = observed_at - timedelta(seconds=61)
    await db_session.flush()
    db_session.info.pop(API_CAPABILITY_GATE_SNAPSHOT_KEY)
    with pytest.raises(JobCapabilityUnavailable) as stale:
        await require_available_job_type(db_session, "manual_intake")
    assert stale.value.code == "job_capability_unavailable"


@pytest.mark.asyncio
async def test_api_gate_enforces_queue_ceiling_and_rejects_without_inserting(db_session):
    observed_at = datetime.now(UTC)
    db_session.info[API_CAPABILITY_GATE_SESSION_KEY] = True
    db_session.add(_heartbeat(observed_at, job_types=["manual_intake"]))
    await db_session.flush()
    repository = JobRepository(db_session)

    accepted = await repository.enqueue_job(
        job_type="manual_intake",
        payload={"kind": "text"},
        idempotency_key="phase9-gate-accepted",
        origin=JobOrigin.MANUAL,
    )
    assert accepted.created is True

    with pytest.raises(JobCapabilityUnavailable) as full:
        await require_available_job_type(
            db_session,
            "manual_intake",
            config=Settings(capability_queue_ceiling=1),
        )
    assert full.value.code == "job_queue_capacity_exceeded"

    heartbeat = await db_session.scalar(select(RuntimeHeartbeat))
    heartbeat.observed_at = observed_at - timedelta(seconds=61)
    await db_session.flush()
    db_session.info.pop(API_CAPABILITY_GATE_SNAPSHOT_KEY)
    with pytest.raises(JobCapabilityUnavailable):
        await repository.enqueue_job(
            job_type="ingest.collect",
            payload={},
            idempotency_key="phase9-gate-rejected",
            origin=JobOrigin.MANUAL,
        )
    rejected_count = await db_session.scalar(
        select(func.count()).select_from(WorkflowJob).where(WorkflowJob.idempotency_key == "phase9-gate-rejected")
    )
    assert rejected_count == 0


@pytest.mark.asyncio
async def test_api_gate_allows_idempotent_replay_but_gates_operator_retry(db_session):
    db_session.info[API_CAPABILITY_GATE_SESSION_KEY] = True
    existing = WorkflowJob(
        id=uuid4(),
        job_type="manual_intake",
        status=JobStatus.FAILED,
        payload={},
        result={},
        idempotency_key="phase9-existing",
        origin=JobOrigin.MANUAL,
        max_attempts=3,
    )
    db_session.add(existing)
    await db_session.flush()
    repository = JobRepository(db_session)

    replay = await repository.enqueue_job(
        job_type="manual_intake",
        payload={},
        idempotency_key="phase9-existing",
        origin=JobOrigin.MANUAL,
    )
    assert replay.created is False
    assert replay.job.id == existing.id

    with pytest.raises(JobCapabilityUnavailable) as retry:
        await repository.retry_job(job_id=existing.id)
    assert retry.value.code == "job_capability_unavailable"
    assert existing.status == JobStatus.FAILED
