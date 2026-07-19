from __future__ import annotations

from typing import Any

from app.jobs.errors import RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, job_payload_copy


def _build_workflow():
    from app.ingestion.workflow import IngestionWorkflow

    return IngestionWorkflow()


def _build_job_repository(session):
    return JobRepository(session)


async def handle_ingest_collect(job: JobExecution, context: JobContext) -> dict[str, Any]:
    payload = job_payload_copy(job)
    workflow = _build_workflow()
    stats = await workflow.run(
        session=context.session,
        platforms=payload.get("platforms"),
        source_ids=payload.get("source_ids"),
        trigger="workflow_job",
    )
    if int(stats.get("failed", 0)) > 0:
        raise RetryableJobError(code="ingest_partial", message="One or more ingestion sources failed")
    await _build_job_repository(context.session).enqueue_job(
        job_type="story.group_pending",
        payload={"limit": 100, "root_ingest_job_id": str(job.id)},
        idempotency_key=f"story-group:{job.id}",
        origin=JobOrigin.AUTOMATION,
    )
    return stats
