from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.core.faults import FaultInjector, NoopFaultInjector
from app.exports.models import BuildExportPayload
from app.exports.service import ExportContractError, ExportService
from app.jobs.errors import PermanentJobError
from app.jobs.registry import JobContext, JobHandler


def build_export_handler(
    *,
    export_root: Path,
    media_root: Path,
    fault_injector: FaultInjector | None = None,
) -> JobHandler:
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()

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
        await injector.hit(
            "export.after_manifest_before_commit",
            {
                "export_id": str(artifact.export_id),
                "content_pack_id": str(artifact.content_pack_id),
            },
        )
        return artifact.model_dump(mode="json")

    return handle
