from __future__ import annotations

from typing import Any

from app.jobs.errors import RetryableJobError
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext


def _build_workflow():
    from app.ingestion.workflow import IngestionWorkflow

    return IngestionWorkflow()


async def handle_ingest_collect(job: WorkflowJob, context: JobContext) -> dict[str, Any]:
    workflow = _build_workflow()
    stats = await workflow.run(
        session=context.session,
        platforms=job.payload.get("platforms"),
        source_ids=job.payload.get("source_ids"),
        trigger="workflow_job",
    )
    if int(stats.get("failed", 0)) > 0:
        raise RetryableJobError(code="ingest_partial", message="One or more ingestion sources failed")
    return stats
