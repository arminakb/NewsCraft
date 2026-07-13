from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.exports.models import BuildExportPayload
from app.exports.service import ExportContractError, ExportService
from app.jobs.errors import PermanentJobError
from app.jobs.registry import JobContext, JobHandler


def build_export_handler(*, export_root: Path, media_root: Path) -> JobHandler:
    async def handle(job, context: JobContext) -> dict:
        try:
            payload = BuildExportPayload.model_validate(job.payload)
        except ValidationError as exc:
            raise PermanentJobError(
                code="export_job_payload_invalid",
                message="Export job payload does not satisfy the immutable revision contract",
            ) from exc
        try:
            artifact = await ExportService(
                context.session,
                export_root=export_root,
                media_root=media_root,
            ).build_from_payload(
                payload,
                export_id=job.id,
                created_at=job.created_at,
            )
        except ExportContractError as exc:
            raise PermanentJobError(code=exc.code, message=str(exc)) from exc
        return artifact.model_dump(mode="json")

    return handle
