from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import WorkflowState
from app.db.models import ContentProductionRun, DraftQualityReport, TelegramDraft, TelegramPostPackage, VisualBrief


class TelegramPackageService:
    def __init__(self, session):
        self.session = session

    async def build_package(
        self,
        *,
        run: ContentProductionRun,
        draft: TelegramDraft,
        quality_report: DraftQualityReport,
        visual_brief: VisualBrief | None = None,
        command_id: uuid.UUID | None = None,
    ) -> TelegramPostPackage:
        package_id = artifact_id(command_id or run.id, "telegram_post_package", str(draft.id))

        async def create() -> TelegramPostPackage:
            repository = ContentProductionRepository(self.session)
            if run.state in {
                WorkflowState.QUALITY_PASSED.value,
                WorkflowState.MEDIA_READY.value,
                WorkflowState.IMAGE_READY.value,
            }:
                await repository.transition_run(run, WorkflowState.PACKAGING, current_step="telegram_package")

            package_payload = build_package_payload(
                draft=draft,
                quality_report=quality_report,
                visual_brief=visual_brief,
            )
            package = TelegramPostPackage(
                id=package_id,
                production_run_id=run.id,
                draft_id=draft.id,
                media_asset_id=visual_brief.selected_media_asset_id if visual_brief else None,
                image_request_id=visual_brief.id if visual_brief and visual_brief.needs_generation else None,
                package_json=package_payload,
                approval_status="pending",
            )
            self.session.add(package)
            await self.session.flush()
            await repository.transition_run(run, WorkflowState.PACKAGE_READY, current_step="telegram_package")
            await repository.transition_run(run, WorkflowState.FINAL_APPROVAL_PENDING, current_step="final_approval")
            return package

        return await create_or_get_artifact(self.session, TelegramPostPackage, package_id, create)

    async def approve(self, *, run: ContentProductionRun, package: TelegramPostPackage) -> TelegramPostPackage:
        if run.state != WorkflowState.FINAL_APPROVAL_PENDING.value:
            raise ValueError("package is not waiting for final approval")
        package.approval_status = "approved"
        package.approved_at = datetime.now(UTC)
        await self.session.flush()
        await ContentProductionRepository(self.session).transition_run(
            run,
            WorkflowState.FINAL_APPROVED,
            current_step="final_approval",
        )
        return package

    async def reject(self, *, run: ContentProductionRun, package: TelegramPostPackage) -> TelegramPostPackage:
        package.approval_status = "rejected"
        package.rejected_at = datetime.now(UTC)
        await self.session.flush()
        await ContentProductionRepository(self.session).transition_run(
            run,
            WorkflowState.FINAL_REJECTED,
            current_step="final_approval",
        )
        return package

    async def request_revision(self, *, run: ContentProductionRun, package: TelegramPostPackage) -> TelegramPostPackage:
        package.approval_status = "revision_requested"
        package.revision_requested_at = datetime.now(UTC)
        await self.session.flush()
        await ContentProductionRepository(self.session).transition_run(
            run,
            WorkflowState.REVISION_REQUESTED,
            current_step="final_approval",
        )
        return package


def build_package_payload(
    *,
    draft: TelegramDraft,
    quality_report: DraftQualityReport,
    visual_brief: VisualBrief | None = None,
) -> dict:
    warnings = list(draft.warnings_json or [])
    warnings.extend(quality_report.factuality_warnings_json or [])
    warnings.extend(quality_report.style_warnings_json or [])
    media = _media_payload(visual_brief)
    dispatch_readiness = "blocked_pending_final_approval"
    return {
        "platform": "telegram",
        "post_text": draft.draft_text,
        "source_links": draft.source_links_json,
        "hashtags": draft.hashtags_json,
        "quality_report": {
            "id": str(quality_report.id),
            "status": quality_report.status,
            "score": str(quality_report.score),
            "required_revisions": quality_report.required_revisions_json,
        },
        "media": media,
        "warnings": list(dict.fromkeys(warnings)),
        "approval_status": "pending",
        "dispatch_readiness": dispatch_readiness,
    }


def _media_payload(visual_brief: VisualBrief | None) -> dict:
    if not visual_brief:
        return {"status": "missing", "warning": "no_media_or_visual_brief"}
    if visual_brief.selected_media_asset_id:
        return {"status": "selected", "media_asset_id": str(visual_brief.selected_media_asset_id)}
    return {
        "status": visual_brief.status,
        "image_request_id": str(visual_brief.id),
        "needs_generation": visual_brief.needs_generation,
        "visual_prompt": visual_brief.visual_prompt,
        "warning": visual_brief.error_message,
    }
