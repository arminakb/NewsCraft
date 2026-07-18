from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.jobs.models import RuntimeHeartbeat, WorkflowEvent, WorkflowJob
from app.jobs.types import JobOrigin, JobStatus
from app.operations.health import HealthState, OperationalHealthService, ReadinessService


def _config(tmp_path, **changes) -> Settings:
    media = tmp_path / "media"
    exports = tmp_path / "exports"
    media.mkdir(exist_ok=True)
    exports.mkdir(exist_ok=True)
    values = {
        "media_root": str(media),
        "export_root": str(exports),
        "expected_runtime_component_ids": "worker-source-generation,scheduler",
        "readiness_required_capabilities": "source",
    }
    values.update(changes)
    return Settings(**values)


@pytest.mark.asyncio
async def test_postgres_readiness_and_operational_health_use_real_schema_queue_and_heartbeat(
    db_session,
    tmp_path,
):
    observed_at = datetime.now(UTC)
    heartbeat = RuntimeHeartbeat(
        component_id="worker-source-generation",
        component_type="worker",
        capabilities=["ingestion", "source", "generation"],
        observed_at=observed_at,
        runtime_metadata={
            "job_types": ["ingest.collect"],
            "state": "idle",
            "last_success_at": observed_at.isoformat(),
            "active_work_started_at": None,
            "active_work_type": None,
        },
    )
    due_job = WorkflowJob(
        id=uuid4(),
        job_type="ingest.collect",
        status=JobStatus.QUEUED,
        payload={},
        result={},
        idempotency_key=f"phase9:{uuid4()}",
        origin=JobOrigin.SCHEDULER,
        scheduled_for=observed_at - timedelta(seconds=10),
        max_attempts=3,
    )
    db_session.add_all([heartbeat, due_job])
    await db_session.flush()
    config = _config(tmp_path)

    readiness = await ReadinessService(db_session, config=config).snapshot()
    operational = await OperationalHealthService(db_session, config=config).snapshot()

    assert readiness.status == "ready"
    assert operational.dependencies["database"].state == HealthState.HEALTHY
    assert operational.dependencies["schema"].state == HealthState.HEALTHY
    assert operational.generated_at >= heartbeat.observed_at
    assert operational.components["worker-source-generation"].state == HealthState.HEALTHY
    assert operational.components["scheduler"].state == HealthState.UNKNOWN
    queue = next(item for item in operational.queues if item.job_type == "ingest.collect")
    assert queue.due_count == 1
    assert queue.healthy_compatible_workers == 1
    assert queue.state == HealthState.HEALTHY


@pytest.mark.asyncio
async def test_postgres_due_work_detects_wrong_worker_capability_and_index_exists(
    db_session,
    tmp_path,
):
    observed_at = datetime.now(UTC)
    db_session.add_all(
        [
            RuntimeHeartbeat(
                component_id="worker-publishing",
                component_type="worker",
                capabilities=["publishing"],
                observed_at=observed_at,
                runtime_metadata={
                    "job_types": ["telegram.publish"],
                    "state": "idle",
                    "last_success_at": observed_at.isoformat(),
                },
            ),
            WorkflowJob(
                id=uuid4(),
                job_type="build_export",
                status=JobStatus.QUEUED,
                payload={},
                result={},
                idempotency_key=f"phase9:{uuid4()}",
                origin=JobOrigin.MANUAL,
                scheduled_for=observed_at,
                max_attempts=3,
            ),
        ]
    )
    await db_session.flush()

    operational = await OperationalHealthService(
        db_session,
        config=_config(
            tmp_path,
            expected_runtime_component_ids="worker-publishing",
            readiness_required_capabilities="",
        ),
    ).snapshot()

    queue = next(item for item in operational.queues if item.job_type == "build_export")
    assert queue.state == HealthState.UNAVAILABLE
    assert queue.code == "no_compatible_worker"
    assert any(alert.code == "no_compatible_worker" for alert in operational.alerts)
    index_exists = await db_session.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND indexname = 'ix_workflow_jobs_operational_health')"
        )
    )
    assert index_exists is True


@pytest.mark.asyncio
async def test_postgres_operational_health_identifies_terminal_poison_recovery_safely(
    db_session,
    tmp_path,
):
    observed_at = datetime.now(UTC)
    poison_job = WorkflowJob(
        id=uuid4(),
        job_type="build_export",
        status=JobStatus.FAILED,
        payload={},
        result={},
        idempotency_key=f"phase3-poison:{uuid4()}",
        origin=JobOrigin.MANUAL,
        attempt_count=3,
        max_attempts=3,
        error_class="retryable",
        error_code="worker_lease_expired",
        error_message="Worker lease expired after the final configured attempt",
        finished_at=observed_at,
    )
    db_session.add(poison_job)
    await db_session.flush()
    for offset in (3, 2, 1):
        db_session.add(
            WorkflowEvent(
                workflow_job_id=poison_job.id,
                event_type="job.lease_expired",
                actor="system",
                event_data={},
                created_at=observed_at - timedelta(minutes=offset),
            )
        )
    await db_session.flush()

    operational = await OperationalHealthService(
        db_session,
        config=_config(
            tmp_path,
            expected_runtime_component_ids="",
            readiness_required_capabilities="",
        ),
    ).snapshot()

    recovery = next(item for item in operational.recoveries if item.job_id == str(poison_job.id))
    assert recovery.code == "poison_job_terminal"
    assert recovery.recovery_count == 3
    assert recovery.attempt_count == recovery.max_attempts == 3
    assert any(
        alert.code == "poison_job_terminal" and alert.scope == f"job:{poison_job.id}" for alert in operational.alerts
    )
    assert operational.metrics["poison_jobs_terminal"] == 1
