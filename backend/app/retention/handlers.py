from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.faults import FaultInjector
from app.jobs.errors import PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy
from app.retention.service import RetentionConflict


class RetentionJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    preview_token: str = Field(pattern=r"^[0-9a-f]{64}$")


def _retention_service(session: Any):
    from app.retention.service import RetentionService

    return RetentionService(session)


def build_retention_handler(
    *,
    export_root: Path,
    media_root: Path,
    fault_injector: FaultInjector | None = None,
) -> JobHandler:
    async def handle(job: JobExecution, context: JobContext) -> dict[str, Any]:
        try:
            payload = RetentionJobPayload.model_validate(job_payload_copy(job))
        except ValidationError as exc:
            raise PermanentJobError(
                code="retention_job_payload_invalid",
                message="Retention job payload must contain only a server run ID and preview token",
            ) from exc

        service = _retention_service(context.session)
        try:
            await service.execute_db_phase(
                payload.run_id,
                payload.preview_token,
                export_root=export_root,
                media_root=media_root,
            )
            await context.session.commit()
            filesystem_options: dict[str, Any] = {
                "export_root": export_root,
                "media_root": media_root,
            }
            if fault_injector is not None:
                filesystem_options["fault_injector"] = fault_injector
            run = await service.finish_filesystem_phase(payload.run_id, **filesystem_options)
        except RetentionConflict as exc:
            raise PermanentJobError(
                code="retention_conflict",
                message=str(exc),
            ) from exc
        if run.status == "partial":
            raise RetryableJobError(
                code="retention_cleanup_partial",
                message="Retention filesystem cleanup remains partial",
            )
        return {"run_id": str(run.id), "status": str(run.status)}

    return handle
