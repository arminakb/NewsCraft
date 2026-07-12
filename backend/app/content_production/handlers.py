from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.content_production.briefs import EditorialBriefService
from app.content_production.candidates import CandidateSelectionService
from app.content_production.dispatch import TelegramDispatchService
from app.content_production.enrichment import (
    ArticleExtractionProvider,
    ArticleExtractionService,
    WebEnrichmentProvider,
    WebEnrichmentService,
)
from app.content_production.events import WorkflowEventType
from app.content_production.idempotency import artifact_id
from app.content_production.llm import LLMProvider, LLMProviderError
from app.content_production.media import ImageGenerationProvider, MediaResolverService
from app.content_production.orchestration import EventDispatcher
from app.content_production.packages import TelegramPackageService
from app.content_production.quality import DraftQualityService
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import InvalidWorkflowTransition, WorkflowState
from app.content_production.sufficiency import (
    ContentSufficiencyService,
    SufficiencyInputAssembler,
    SufficiencyStage,
)
from app.content_production.telegram_drafts import TelegramDraftService
from app.content_production.tracing import WorkflowTraceService
from app.db.models import (
    ArticleExtractionResult,
    CandidateShortlist,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    ContentSufficiencyReport,
    DraftQualityReport,
    EditorialBrief,
    MediaAsset,
    TelegramDispatchRequest,
    TelegramDraft,
    TelegramPostPackage,
    VisualBrief,
    WebEnrichmentResult,
    WorkflowEvent,
)


class InvalidWorkflowEventPayload(ValueError):
    pass


class CoreWorkflowEventHandlers:
    def __init__(
        self,
        session,
        *,
        extraction_client: httpx.AsyncClient | None = None,
        extraction_provider: ArticleExtractionProvider | None = None,
        enrichment_provider: WebEnrichmentProvider | None = None,
        llm_provider: LLMProvider | None = None,
        llm_timeout_seconds: float = 45.0,
        llm_max_output_tokens: int = 1800,
        image_provider: ImageGenerationProvider | None = None,
        telegram_bot_token: str | None = None,
        telegram_channel_id: str | None = None,
    ) -> None:
        self.session = session
        self.repository = ContentProductionRepository(session)
        self.extraction_client = extraction_client
        self.extraction_provider = extraction_provider
        self.enrichment_provider = enrichment_provider
        self.llm_provider = llm_provider
        self.llm_timeout_seconds = llm_timeout_seconds
        self.llm_max_output_tokens = llm_max_output_tokens
        self.image_provider = image_provider
        self.telegram_bot_token = telegram_bot_token
        self.telegram_channel_id = telegram_channel_id

    async def content_production_request_created(self, event: WorkflowEvent) -> None:
        request = await self._request(event)
        if request.status != WorkflowState.CREATED.value:
            raise InvalidWorkflowTransition(f"new request event cannot advance request status {request.status}")
        await self._emit(
            event,
            WorkflowEventType.CANDIDATE_SELECTION_REQUESTED,
            aggregate_type="content_production_request",
            aggregate_id=request.id,
            payload={"request_id": str(request.id), "max_candidates": request.max_candidates},
        )

    async def candidate_selection_requested(self, event: WorkflowEvent) -> None:
        request = await self._request(event)
        if request.status not in {
            WorkflowState.CREATED.value,
            WorkflowState.SELECTING.value,
            WorkflowState.SHORTLIST_APPROVAL_PENDING.value,
            WorkflowState.SHORTLIST_READY.value,
        }:
            raise InvalidWorkflowTransition(f"candidate selection cannot start from request status {request.status}")
        if request.status in {WorkflowState.CREATED.value, WorkflowState.SELECTING.value}:
            request.status = WorkflowState.SELECTING.value
        shortlist = await CandidateSelectionService(self.session).prepare_shortlist(request, command_id=event.event_id)
        await self._emit(
            event,
            WorkflowEventType.CANDIDATE_SHORTLIST_PREPARED,
            aggregate_type="content_production_request",
            aggregate_id=request.id,
            payload={
                "request_id": str(request.id),
                "selection_execution_id": str(event.event_id),
                "candidate_count": len(shortlist),
                "content_item_ids": [str(candidate.content_item_id) for candidate in shortlist],
            },
        )

    async def candidate_shortlist_prepared(self, event: WorkflowEvent) -> None:
        request = await self._request(event)
        selection_execution_id = self._required_uuid(event, "selection_execution_id")
        candidate_count = self._required_int(event, "candidate_count", minimum=0)
        candidates = await self._shortlist(request.id, selection_execution_id)
        if candidate_count != len(candidates):
            raise InvalidWorkflowEventPayload("candidate_count does not match the persisted shortlist")
        if not candidates:
            request.status = WorkflowState.SHORTLIST_READY.value
            await self.session.flush()
            return
        if request.status != WorkflowState.SHORTLIST_APPROVAL_PENDING.value:
            raise InvalidWorkflowTransition(f"shortlist is not awaiting approval: {request.status}")
        await self._emit(
            event,
            WorkflowEventType.CANDIDATE_SHORTLIST_APPROVAL_REQUESTED,
            aggregate_type="content_production_request",
            aggregate_id=request.id,
            payload={
                "request_id": str(request.id),
                "selection_execution_id": str(selection_execution_id),
                "candidate_count": len(candidates),
            },
        )

    async def candidate_shortlist_approval_requested(self, event: WorkflowEvent) -> None:
        request = await self._request(event)
        self._required_uuid(event, "selection_execution_id")
        if request.status != WorkflowState.SHORTLIST_APPROVAL_PENDING.value:
            raise InvalidWorkflowTransition(f"shortlist approval gate is not active: {request.status}")

    async def candidate_shortlist_approved(self, event: WorkflowEvent) -> None:
        request = await self._request(event)
        selection_execution_id = self._required_uuid(event, "selection_execution_id")
        content_item_ids = self._required_uuid_list(event, "content_item_ids")
        candidates = await self._shortlist(request.id, selection_execution_id)
        selected = [candidate for candidate in candidates if candidate.content_item_id in content_item_ids]
        if len(selected) != len(content_item_ids):
            raise LookupError("one or more approved shortlist candidates were not found")
        if any(candidate.approval_status != "approved" for candidate in selected):
            raise InvalidWorkflowTransition("shortlist approval event requires explicitly approved candidates")

        request.status = WorkflowState.SHORTLIST_APPROVED.value
        for candidate in selected:
            run_id = artifact_id(event.event_id, "content_production_run", str(candidate.content_item_id))
            run = await self.session.get(ContentProductionRun, run_id)
            if run is None:
                run = await self.repository.create_run(
                    request_id=request.id,
                    content_item_id=candidate.content_item_id,
                    platform=request.platform,
                    initial_state=WorkflowState.SHORTLIST_APPROVED,
                    command_id=event.event_id,
                )
            await self._emit_run_event(
                event,
                WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
                run,
                payload={"stage": SufficiencyStage.ORIGINAL.value},
            )

    async def candidate_shortlist_rejected(self, event: WorkflowEvent) -> None:
        request = await self._request(event)
        selection_execution_id = self._required_uuid(event, "selection_execution_id")
        content_item_ids = self._required_uuid_list(event, "content_item_ids")
        candidates = await self._shortlist(request.id, selection_execution_id)
        selected = [candidate for candidate in candidates if candidate.content_item_id in content_item_ids]
        if len(selected) != len(content_item_ids):
            raise LookupError("one or more rejected shortlist candidates were not found")
        if any(candidate.approval_status != "rejected" for candidate in selected):
            raise InvalidWorkflowTransition("shortlist rejection event requires explicitly rejected candidates")
        request.status = WorkflowState.SHORTLIST_REJECTED.value
        await self.session.flush()

    async def content_sufficiency_check_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        stage = self._sufficiency_stage(event)
        extraction_result_id = self._optional_uuid(event, "extraction_result_id")
        enrichment_result_id = self._optional_uuid(event, "enrichment_result_id")
        item = await self._required(ContentItem, run.content_item_id, "content item")
        inputs = await SufficiencyInputAssembler(self.session).assemble(
            run=run,
            item=item,
            stage=stage,
            source_event_id=event.event_id,
            extraction_result_id=extraction_result_id,
            enrichment_result_id=enrichment_result_id,
        )
        report = await self._command_artifact(event, ContentSufficiencyReport, "content_sufficiency_report")
        if report is None:
            self._require_run_state(
                run,
                WorkflowState.SHORTLIST_APPROVED,
                WorkflowState.ARTICLE_EXTRACTED,
                WorkflowState.ENRICHED,
            )
            if run.state in {WorkflowState.ARTICLE_EXTRACTED.value, WorkflowState.ENRICHED.value}:
                await self.repository.transition_run(
                    run,
                    WorkflowState.SUFFICIENCY_CHECKING,
                    current_step="content_sufficiency",
                )
            report = await ContentSufficiencyService(self.session).check_run(
                run,
                item,
                inputs=inputs,
                command_id=event.event_id,
            )
        await self._emit_run_event(
            event,
            WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED,
            run,
            payload={
                "report_id": str(report.id),
                "stage": stage.value,
                "status": report.status,
                "extraction_result_id": str(inputs.extraction.id) if inputs.extraction else None,
                "enrichment_result_id": str(inputs.enrichment.id) if inputs.enrichment else None,
                "reasons": report.reasons_json,
            },
        )

    async def content_sufficiency_checked(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        report_id = self._required_uuid(event, "report_id")
        report = await self._required(ContentSufficiencyReport, report_id, "sufficiency report")
        stage = self._sufficiency_stage(event)
        status = self._required_str(event, "status")
        if (
            report.production_run_id != run.id
            or report.status != status
            or report.input_snapshot_json.get("stage") != stage.value
        ):
            raise InvalidWorkflowEventPayload("sufficiency event does not match its persisted report")
        extraction_result_id = self._optional_uuid(event, "extraction_result_id")
        enrichment_result_id = self._optional_uuid(event, "enrichment_result_id")
        routing_payload = {
            "report_id": str(report.id),
            "stage": stage.value,
            "extraction_result_id": str(extraction_result_id) if extraction_result_id else None,
            "enrichment_result_id": str(enrichment_result_id) if enrichment_result_id else None,
        }
        if status == "sufficient":
            await self._emit_run_event(
                event,
                WorkflowEventType.EDITORIAL_BRIEF_REQUESTED,
                run,
                payload=routing_payload,
            )
            return
        if status in {"evaluation_failed", "rejected"}:
            await self._emit_run_event(
                event,
                WorkflowEventType.PRODUCTION_RUN_FAILED,
                run,
                payload={
                    **routing_payload,
                    "failure_type": "sufficiency_evaluation_failed" if status == "evaluation_failed" else "rejected",
                    "failure_reason": "; ".join(report.reasons_json) or "sufficiency evaluation failed",
                },
            )
            return
        if status not in {"partial", "insufficient"}:
            raise InvalidWorkflowEventPayload(f"unsupported sufficiency status: {status}")
        if stage == SufficiencyStage.ORIGINAL:
            await self._emit_run_event(
                event,
                WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED,
                run,
                payload=routing_payload,
            )
            return
        if stage == SufficiencyStage.POST_EXTRACTION:
            await self._emit_run_event(
                event,
                WorkflowEventType.WEB_ENRICHMENT_REQUESTED,
                run,
                payload=routing_payload,
            )
            return
        relevance_review_required = False
        if enrichment_result_id is not None:
            enrichment = await self._required(WebEnrichmentResult, enrichment_result_id, "web enrichment result")
            relevance_review_required = any(
                finding.get("relevance_status") == "ambiguous"
                and finding.get("accepted_for_evidence") is not True
                for finding in enrichment.findings_json
                if isinstance(finding, dict)
            )
        await self._emit_run_event(
            event,
            WorkflowEventType.PRODUCTION_RUN_FAILED,
            run,
            payload={
                **routing_payload,
                "failure_type": (
                    "enrichment_relevance_human_review_required"
                    if relevance_review_required
                    else "terminal_content_insufficient"
                ),
                "failure_reason": (
                    "enrichment relevance is ambiguous and requires human review"
                    if relevance_review_required
                    else "content remains insufficient after extraction and enrichment"
                ),
                "human_review_required": relevance_review_required,
                "extraction_attempted": extraction_result_id is not None,
                "enrichment_attempted": enrichment_result_id is not None,
                "no_more_automatic_stages": True,
            },
        )

    async def article_extraction_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        result = await self._command_artifact(event, ArticleExtractionResult, "article_extraction_result")
        if result is None:
            self._require_run_state(run, WorkflowState.SUFFICIENCY_PARTIAL, WorkflowState.SUFFICIENCY_INSUFFICIENT)
            item = await self._required(ContentItem, run.content_item_id, "content item")
            result = await ArticleExtractionService(
                self.session,
                client=self.extraction_client,
                provider=self.extraction_provider,
            ).extract_for_run(
                run,
                item,
                command_id=event.event_id,
            )
        next_type = (
            WorkflowEventType.ARTICLE_EXTRACTED
            if result.status in {"ok", "fallback"}
            else WorkflowEventType.ARTICLE_EXTRACTION_FAILED
        )
        await self._emit_run_event(
            event,
            next_type,
            run,
            payload={
                "extraction_result_id": str(result.id),
                "status": result.status,
                "source_stage": event.payload.get("stage"),
            },
        )

    async def article_extracted(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.ARTICLE_EXTRACTED)
        result = await self._event_artifact(event, "extraction_result_id", ArticleExtractionResult)
        if result.production_run_id != run.id or result.status not in {"ok", "fallback"}:
            raise InvalidWorkflowEventPayload("article extraction completion is inconsistent")
        await self._emit_run_event(
            event,
            WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
            run,
            payload={
                "stage": SufficiencyStage.POST_EXTRACTION.value,
                "extraction_result_id": str(result.id),
            },
        )

    async def article_extraction_failed(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.ARTICLE_EXTRACTING)
        result = await self._event_artifact(event, "extraction_result_id", ArticleExtractionResult)
        if result.production_run_id != run.id or result.status != "failed":
            raise InvalidWorkflowEventPayload("article extraction failure is inconsistent")
        await self._emit_run_event(
            event,
            WorkflowEventType.WEB_ENRICHMENT_REQUESTED,
            run,
            payload={
                "stage": SufficiencyStage.POST_EXTRACTION.value,
                "extraction_result_id": str(result.id),
                "extraction_failure_type": (
                    "extraction_unavailable" if result.error_message == "missing_source_url" else "technical"
                ),
                "extraction_error": result.error_message,
            },
        )

    async def web_enrichment_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        result = await self._command_artifact(event, WebEnrichmentResult, "web_enrichment_result")
        if result is None:
            self._require_run_state(
                run,
                WorkflowState.SUFFICIENCY_PARTIAL,
                WorkflowState.SUFFICIENCY_INSUFFICIENT,
                WorkflowState.ARTICLE_EXTRACTED,
                WorkflowState.ARTICLE_EXTRACTING,
            )
            if run.state == WorkflowState.ARTICLE_EXTRACTING.value:
                await self.repository.transition_run(run, WorkflowState.ENRICHING, current_step="web_enrichment")
            item = await self._required(ContentItem, run.content_item_id, "content item")
            result = await WebEnrichmentService(self.session, provider=self.enrichment_provider).enrich_run(
                run,
                item,
                command_id=event.event_id,
            )
        next_type = WorkflowEventType.WEB_ENRICHED if result.status == "ok" else WorkflowEventType.WEB_ENRICHMENT_FAILED
        await self._emit_run_event(
            event,
            next_type,
            run,
            payload={
                "enrichment_result_id": str(result.id),
                "extraction_result_id": event.payload.get("extraction_result_id"),
                "status": result.status,
                "provider_name": result.provider_name,
            },
        )

    async def web_enriched(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.ENRICHED)
        result = await self._event_artifact(event, "enrichment_result_id", WebEnrichmentResult)
        if result.production_run_id != run.id or result.status != "ok":
            raise InvalidWorkflowEventPayload("web enrichment completion is inconsistent")
        await self._emit_run_event(
            event,
            WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
            run,
            payload={
                "stage": SufficiencyStage.POST_ENRICHMENT.value,
                "extraction_result_id": event.payload.get("extraction_result_id"),
                "enrichment_result_id": str(result.id),
            },
        )

    async def web_enrichment_failed(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.ENRICHING)
        result = await self._event_artifact(event, "enrichment_result_id", WebEnrichmentResult)
        if result.production_run_id != run.id or result.status == "ok":
            raise InvalidWorkflowEventPayload("web enrichment failure is inconsistent")
        await self._emit_run_event(
            event,
            WorkflowEventType.PRODUCTION_RUN_FAILED,
            run,
            payload={
                "failure_type": "enrichment_technical_failure",
                "failure_reason": result.error_message or "web enrichment unavailable",
                "provider_name": result.provider_name,
                "extraction_result_id": event.payload.get("extraction_result_id"),
                "enrichment_result_id": str(result.id),
                "extraction_available": event.payload.get("extraction_result_id") is not None,
                "enrichment_attempted": True,
                "current_sufficiency_state": run.state,
                "no_more_automatic_stages": True,
            },
        )

    async def editorial_brief_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        run_id = run.id
        brief = await self._command_artifact(event, EditorialBrief, "editorial_brief")
        if brief is None:
            self._require_run_state(run, WorkflowState.SUFFICIENCY_SUFFICIENT)
            item = await self._required(ContentItem, run.content_item_id, "content item")
            request = await self._required(ContentProductionRequest, run.request_id, "content production request")
            extraction = await self._optional_event_artifact(event, "extraction_result_id", ArticleExtractionResult)
            enrichment = await self._optional_event_artifact(event, "enrichment_result_id", WebEnrichmentResult)
            if extraction is not None:
                self._require_artifact_run(extraction, run)
            if enrichment is not None:
                self._require_artifact_run(enrichment, run)
            try:
                brief = await EditorialBriefService(
                    self.session,
                    provider=self.llm_provider,
                    timeout_seconds=self.llm_timeout_seconds,
                    max_output_tokens=self.llm_max_output_tokens,
                ).create_brief(
                    run=run,
                    item=item,
                    request=request,
                    extraction=extraction,
                    enrichment=enrichment,
                    command_id=event.event_id,
                )
            except LLMProviderError as exc:
                if exc.retryable:
                    raise
                await self._emit_llm_failure(event, run_id, "editorial_brief", exc)
                return
        await self._emit_run_event(
            event,
            WorkflowEventType.EDITORIAL_BRIEF_CREATED,
            run,
            payload={"brief_id": str(brief.id)},
        )

    async def editorial_brief_created(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.BRIEF_READY)
        brief = await self._event_artifact(event, "brief_id", EditorialBrief)
        self._require_artifact_run(brief, run)
        await self._emit_run_event(
            event,
            WorkflowEventType.DRAFT_GENERATION_REQUESTED,
            run,
            payload={"brief_id": str(brief.id)},
        )

    async def draft_generation_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        run_id = run.id
        brief = await self._event_artifact(event, "brief_id", EditorialBrief, fallback_latest_run_id=run.id)
        self._require_artifact_run(brief, run)
        draft = await self._command_artifact(event, TelegramDraft, "telegram_draft", str(brief.id))
        if draft is None:
            self._require_run_state(run, WorkflowState.BRIEF_READY)
            try:
                draft = await TelegramDraftService(
                    self.session,
                    provider=self.llm_provider,
                    timeout_seconds=self.llm_timeout_seconds,
                    max_output_tokens=self.llm_max_output_tokens,
                ).create_draft(run=run, brief=brief, command_id=event.event_id)
            except LLMProviderError as exc:
                if exc.retryable:
                    raise
                await self._emit_llm_failure(event, run_id, "persian_telegram_draft", exc)
                return
        await self._emit_run_event(
            event,
            WorkflowEventType.DRAFT_GENERATED,
            run,
            payload={"draft_id": str(draft.id), "brief_id": str(brief.id)},
        )

    async def draft_generated(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.DRAFT_READY)
        draft = await self._event_artifact(event, "draft_id", TelegramDraft)
        self._require_artifact_run(draft, run)
        await self._emit_run_event(
            event,
            WorkflowEventType.DRAFT_QUALITY_CHECK_REQUESTED,
            run,
            payload={"draft_id": str(draft.id), "brief_id": str(draft.brief_id)},
        )

    async def draft_quality_check_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        run_id = run.id
        draft = await self._event_artifact(event, "draft_id", TelegramDraft, fallback_latest_run_id=run.id)
        brief = await self._required(EditorialBrief, draft.brief_id, "editorial brief")
        report = await self._command_artifact(event, DraftQualityReport, "draft_quality_report", str(draft.id))
        if report is None:
            self._require_run_state(run, WorkflowState.DRAFT_READY)
            try:
                report = await DraftQualityService(
                    self.session,
                    provider=self.llm_provider,
                    timeout_seconds=self.llm_timeout_seconds,
                    max_output_tokens=self.llm_max_output_tokens,
                ).check_draft(run=run, draft=draft, brief=brief, command_id=event.event_id)
            except LLMProviderError as exc:
                if exc.retryable:
                    raise
                await self._emit_llm_failure(event, run_id, "draft_quality_evaluation", exc)
                return
        await self._emit_run_event(
            event,
            WorkflowEventType.DRAFT_QUALITY_CHECKED,
            run,
            payload={"quality_report_id": str(report.id), "status": report.status},
        )

    async def draft_quality_checked(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        report = await self._event_artifact(event, "quality_report_id", DraftQualityReport)
        self._require_artifact_run(report, run)
        status = self._required_str(event, "status")
        if report.status != status:
            raise InvalidWorkflowEventPayload("quality status does not match its report")
        if status == "passed":
            self._require_run_state(run, WorkflowState.QUALITY_PASSED)
            await self._emit_run_event(event, WorkflowEventType.MEDIA_RESOLUTION_REQUESTED, run)
            return
        self._require_run_state(run, WorkflowState.QUALITY_FAILED, WorkflowState.REVISION_REQUESTED)
        await self._emit_run_event(
            event,
            WorkflowEventType.DRAFT_REVISION_REQUESTED,
            run,
            payload={"quality_report_id": str(report.id), "status": status},
        )

    async def draft_revision_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.QUALITY_FAILED, WorkflowState.REVISION_REQUESTED)

    async def media_resolution_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        visual = await self._command_artifact(event, VisualBrief, "visual_brief")
        if visual is None:
            self._require_run_state(run, WorkflowState.QUALITY_PASSED)
            item = await self._required(ContentItem, run.content_item_id, "content item")
            media_assets: list[MediaAsset] = []
            if item.primary_image_id:
                primary = await self.session.get(MediaAsset, item.primary_image_id)
                if primary is not None:
                    media_assets.append(primary)
            visual = await MediaResolverService(self.session, image_provider=self.image_provider).resolve(
                run=run,
                item=item,
                media_assets=media_assets,
                command_id=event.event_id,
            )
        next_type = {
            "selected": WorkflowEventType.MEDIA_SELECTED,
            "generated": WorkflowEventType.IMAGE_GENERATED,
        }.get(visual.status, WorkflowEventType.IMAGE_GENERATION_REQUESTED)
        draft, quality = await self._package_inputs(run)
        await self._emit_run_event(
            event,
            next_type,
            run,
            payload={
                "draft_id": str(draft.id),
                "quality_report_id": str(quality.id),
                "visual_brief_id": str(visual.id),
                "status": visual.status,
            },
        )

    async def media_selected(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.MEDIA_READY)
        visual = await self._event_artifact(event, "visual_brief_id", VisualBrief)
        self._require_artifact_run(visual, run)
        if visual.status != "selected":
            raise InvalidWorkflowEventPayload("media selection event requires selected media")
        draft, quality = await self._pinned_package_inputs(event, run)
        await self._emit_run_event(
            event,
            WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED,
            run,
            payload={
                "draft_id": str(draft.id),
                "quality_report_id": str(quality.id),
                "visual_brief_id": str(visual.id),
            },
        )

    async def image_generation_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.IMAGE_GENERATION_PENDING)
        visual = await self._event_artifact(event, "visual_brief_id", VisualBrief)
        self._require_artifact_run(visual, run)
        if not visual.needs_generation:
            raise InvalidWorkflowEventPayload("visual brief does not require image generation")
        # External image generation is intentionally deferred; the workflow pauses here.

    async def image_generated(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        visual = await self._event_artifact(event, "visual_brief_id", VisualBrief)
        self._require_artifact_run(visual, run)
        if run.state == WorkflowState.IMAGE_GENERATION_PENDING.value:
            await self.repository.transition_run(run, WorkflowState.IMAGE_GENERATING, current_step="image_generation")
            await self.repository.transition_run(run, WorkflowState.IMAGE_READY, current_step="image_generation")
        else:
            self._require_run_state(run, WorkflowState.IMAGE_READY)
        visual.status = "generated"
        await self.session.flush()
        draft, quality = await self._pinned_package_inputs(event, run)
        await self._emit_run_event(
            event,
            WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED,
            run,
            payload={
                "draft_id": str(draft.id),
                "quality_report_id": str(quality.id),
                "visual_brief_id": str(visual.id),
            },
        )

    async def image_generation_failed(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.IMAGE_GENERATION_PENDING, WorkflowState.IMAGE_GENERATING)
        visual = await self._event_artifact(event, "visual_brief_id", VisualBrief)
        self._require_artifact_run(visual, run)
        visual.status = "failed"
        visual.error_message = self._required_str(event, "error_message")
        await self.session.flush()
        await self._emit_run_event(
            event,
            WorkflowEventType.PRODUCTION_RUN_FAILED,
            run,
            payload={"failure_reason": visual.error_message},
        )

    async def telegram_package_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        draft, quality = await self._pinned_package_inputs(event, run)
        visual = await self._event_artifact(event, "visual_brief_id", VisualBrief)
        self._require_artifact_run(visual, run)
        package = await self._command_artifact(event, TelegramPostPackage, "telegram_post_package", str(draft.id))
        if package is None:
            self._require_run_state(run, WorkflowState.MEDIA_READY, WorkflowState.IMAGE_READY)
            package = await TelegramPackageService(self.session).build_package(
                run=run,
                draft=draft,
                quality_report=quality,
                visual_brief=visual,
                command_id=event.event_id,
            )
        await self._emit_run_event(
            event,
            WorkflowEventType.TELEGRAM_PACKAGE_READY,
            run,
            payload={"package_id": str(package.id)},
        )

    async def telegram_package_ready(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.FINAL_APPROVAL_PENDING)
        package = await self._event_artifact(event, "package_id", TelegramPostPackage)
        self._require_artifact_run(package, run)
        if package.approval_status != "pending":
            raise InvalidWorkflowEventPayload("new package is not pending final approval")
        await self._emit_run_event(
            event,
            WorkflowEventType.FINAL_APPROVAL_REQUESTED,
            run,
            payload={"package_id": str(package.id)},
        )

    async def final_approval_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.FINAL_APPROVAL_PENDING)
        package = await self._event_artifact(event, "package_id", TelegramPostPackage)
        self._require_artifact_run(package, run)
        # Final approval must come from an explicit operator action.

    async def post_package_approved(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        if await self._followup_exists(event, WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED, run.id):
            return
        self._require_run_state(run, WorkflowState.FINAL_APPROVED)
        package = await self._event_artifact(event, "package_id", TelegramPostPackage, fallback_latest_run_id=run.id)
        self._require_artifact_run(package, run)
        if package.approval_status != "approved":
            raise InvalidWorkflowTransition("dispatch requires explicit package approval")
        await self._emit_run_event(
            event,
            WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED,
            run,
            payload={"package_id": str(package.id)},
        )

    async def post_package_rejected(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.FINAL_REJECTED)
        package = await self._event_artifact(event, "package_id", TelegramPostPackage, fallback_latest_run_id=run.id)
        self._require_artifact_run(package, run)
        if package.approval_status != "rejected":
            raise InvalidWorkflowEventPayload("package rejection event requires a rejected package")

    async def telegram_dispatch_requested(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        package = await self._event_artifact(event, "package_id", TelegramPostPackage, fallback_latest_run_id=run.id)
        self._require_artifact_run(package, run)
        dispatch = await self._command_artifact(
            event,
            TelegramDispatchRequest,
            "telegram_dispatch_request",
            str(package.id),
        )
        if dispatch is None:
            self._require_run_state(run, WorkflowState.FINAL_APPROVED, WorkflowState.DISPATCH_FAILED)
            await TelegramDispatchService(
                self.session,
                bot_token=self.telegram_bot_token,
                channel_id=self.telegram_channel_id,
            ).create_dispatch_request(run=run, package=package, command_id=event.event_id)
        # Dispatch is a handoff only. Publishing is intentionally not automatic.

    async def telegram_post_published(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.DISPATCH_PENDING, WorkflowState.DISPATCHING)
        dispatch = await self._event_artifact(
            event,
            "dispatch_request_id",
            TelegramDispatchRequest,
            fallback_latest_run_id=run.id,
        )
        self._require_artifact_run(dispatch, run)
        if run.state == WorkflowState.DISPATCH_PENDING.value:
            await self.repository.transition_run(run, WorkflowState.DISPATCHING, current_step="telegram_publish")
        await self.repository.transition_run(run, WorkflowState.PUBLISHED, current_step="telegram_publish")
        dispatch.status = "published"
        dispatch.dispatched_at = datetime.now(UTC)
        await self.session.flush()

    async def telegram_post_failed(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        self._require_run_state(run, WorkflowState.DISPATCH_PENDING, WorkflowState.DISPATCHING)
        dispatch = await self._event_artifact(
            event,
            "dispatch_request_id",
            TelegramDispatchRequest,
            fallback_latest_run_id=run.id,
        )
        self._require_artifact_run(dispatch, run)
        reason = self._required_str(event, "error_message")
        await self.repository.transition_run(
            run,
            WorkflowState.DISPATCH_FAILED,
            current_step="telegram_publish",
            failure_reason=reason,
        )
        dispatch.status = "failed"
        dispatch.blocked_reason = reason
        await self.session.flush()

    async def production_run_failed(self, event: WorkflowEvent) -> None:
        run = await self._run(event)
        reason = self._required_str(event, "failure_reason")
        if run.state == WorkflowState.FAILED.value:
            if not run.failure_reason:
                run.failure_reason = reason
                await self.session.flush()
            return
        await self.repository.transition_run(
            run,
            WorkflowState.FAILED,
            current_step="workflow_failure",
            failure_reason=reason,
        )

    async def _emit_llm_failure(
        self,
        event: WorkflowEvent,
        run_id: uuid.UUID,
        operation: str,
        error: LLMProviderError,
    ) -> None:
        await self._emit(
            event,
            WorkflowEventType.PRODUCTION_RUN_FAILED,
            aggregate_type="content_production_run",
            aggregate_id=run_id,
            payload={
                "production_run_id": str(run_id),
                "failure_type": error.code,
                "failure_reason": f"{operation}:{error.code}",
                "operation": operation,
                "retryable": False,
                "diagnostics": error.diagnostics,
            },
        )

    async def _request(self, event: WorkflowEvent) -> ContentProductionRequest:
        request_id = self._aggregate_or_payload_uuid(event, "request_id", "content_production_request")
        return await self._required(ContentProductionRequest, request_id, "content production request")

    async def _run(self, event: WorkflowEvent) -> ContentProductionRun:
        run_id = self._aggregate_or_payload_uuid(event, "production_run_id", "content_production_run")
        return await self._required(ContentProductionRun, run_id, "content production run")

    async def _required(self, model, object_id: uuid.UUID, label: str):
        value = await self.session.get(model, object_id)
        if value is None:
            raise LookupError(f"{label} not found: {object_id}")
        return value

    async def _shortlist(
        self,
        request_id: uuid.UUID,
        selection_execution_id: uuid.UUID,
    ) -> list[CandidateShortlist]:
        rows = await self.session.scalars(
            select(CandidateShortlist).where(
                CandidateShortlist.request_id == request_id,
                CandidateShortlist.selection_execution_id == selection_execution_id,
            )
        )
        return [
            row
            for row in rows
            if row.request_id == request_id and row.selection_execution_id == selection_execution_id
        ]

    async def _package_inputs(self, run: ContentProductionRun) -> tuple[TelegramDraft, DraftQualityReport]:
        quality = await self._latest_required(DraftQualityReport, run.id, "draft quality report")
        if quality.status != "passed":
            raise InvalidWorkflowEventPayload("latest draft quality report is not eligible for packaging")
        draft = await self._required(TelegramDraft, quality.draft_id, "telegram draft")
        self._require_artifact_run(draft, run)
        return draft, quality

    async def _pinned_package_inputs(
        self,
        event: WorkflowEvent,
        run: ContentProductionRun,
    ) -> tuple[TelegramDraft, DraftQualityReport]:
        draft = await self._event_artifact(event, "draft_id", TelegramDraft)
        self._require_artifact_run(draft, run)
        quality = await self._event_artifact(event, "quality_report_id", DraftQualityReport)
        self._require_artifact_run(quality, run)
        if quality.draft_id != draft.id or quality.status != "passed":
            raise InvalidWorkflowEventPayload("quality report does not approve the pinned draft")
        return draft, quality

    async def _runs_for_request(self, request_id: uuid.UUID) -> list[ContentProductionRun]:
        rows = await self.session.scalars(
            select(ContentProductionRun).where(ContentProductionRun.request_id == request_id)
        )
        return [row for row in rows if row.request_id == request_id]

    async def _command_artifact(self, event, model, purpose: str, discriminator: str = ""):
        return await self.session.get(model, artifact_id(event.event_id, purpose, discriminator))

    async def _followup_exists(
        self,
        source: WorkflowEvent,
        event_type: WorkflowEventType,
        aggregate_id: uuid.UUID,
        aggregate_type: str = "content_production_run",
    ) -> bool:
        event_id = uuid.uuid5(source.event_id, f"{event_type.value}:{aggregate_type}:{aggregate_id}")
        return await self.session.get(WorkflowEvent, event_id) is not None

    async def _latest(self, model, run_id: uuid.UUID):
        return await self.session.scalar(
            select(model).where(model.production_run_id == run_id).order_by(model.created_at.desc()).limit(1)
        )

    async def _latest_required(self, model, run_id: uuid.UUID, label: str):
        value = await self._latest(model, run_id)
        if value is None:
            raise LookupError(f"{label} not found for production run: {run_id}")
        return value

    async def _has_run_artifact(self, model, run_id: uuid.UUID) -> bool:
        return await self._latest(model, run_id) is not None

    async def _event_artifact(self, event, key, model, *, fallback_latest_run_id=None):
        raw_value = event.payload.get(key)
        if raw_value is None and fallback_latest_run_id is not None:
            return await self._latest_required(model, fallback_latest_run_id, key)
        artifact_id = self._required_uuid(event, key)
        return await self._required(model, artifact_id, key)

    async def _optional_event_artifact(self, event, key, model):
        object_id = self._optional_uuid(event, key)
        if object_id is None:
            return None
        return await self._required(model, object_id, key)

    def _sufficiency_stage(self, event: WorkflowEvent) -> SufficiencyStage:
        value = self._required_str(event, "stage")
        try:
            return SufficiencyStage(value)
        except ValueError as exc:
            raise InvalidWorkflowEventPayload(f"unsupported sufficiency stage: {value}") from exc

    def _optional_uuid(self, event: WorkflowEvent, key: str) -> uuid.UUID | None:
        value = event.payload.get(key)
        if value is None:
            return None
        return self._coerce_uuid(value, key)

    async def _emit_run_event(
        self,
        source: WorkflowEvent,
        event_type: WorkflowEventType,
        run: ContentProductionRun,
        *,
        payload: dict[str, Any] | None = None,
    ) -> WorkflowEvent:
        values = {"production_run_id": str(run.id), **(payload or {})}
        return await self._emit(
            source,
            event_type,
            aggregate_type="content_production_run",
            aggregate_id=run.id,
            payload=values,
        )

    async def _emit(
        self,
        source: WorkflowEvent,
        event_type: WorkflowEventType,
        *,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> WorkflowEvent:
        event_id = uuid.uuid5(source.event_id, f"{event_type.value}:{aggregate_type}:{aggregate_id}")
        emitted, _ = await self.repository.enqueue_event_once(
            event_id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            correlation_id=source.correlation_id,
            causation_id=source.event_id,
            payload=payload,
        )
        return emitted

    def _aggregate_or_payload_uuid(self, event: WorkflowEvent, key: str, aggregate_type: str) -> uuid.UUID:
        raw_value = event.payload.get(key)
        if raw_value is None and event.aggregate_type == aggregate_type:
            return event.aggregate_id
        return self._coerce_uuid(raw_value, key)

    def _required_uuid(self, event: WorkflowEvent, key: str) -> uuid.UUID:
        return self._coerce_uuid(event.payload.get(key), key)

    def _required_uuid_list(self, event: WorkflowEvent, key: str) -> list[uuid.UUID]:
        values = event.payload.get(key)
        if not isinstance(values, list) or not values:
            raise InvalidWorkflowEventPayload(f"{key} must be a non-empty list of UUIDs")
        parsed = [self._coerce_uuid(value, key) for value in values]
        if len(parsed) != len(set(parsed)):
            raise InvalidWorkflowEventPayload(f"{key} must not contain duplicates")
        return parsed

    def _required_str(self, event: WorkflowEvent, key: str) -> str:
        value = event.payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise InvalidWorkflowEventPayload(f"{key} must be a non-empty string")
        return value.strip()

    def _required_int(self, event: WorkflowEvent, key: str, *, minimum: int) -> int:
        value = event.payload.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise InvalidWorkflowEventPayload(f"{key} must be an integer >= {minimum}")
        return value

    @staticmethod
    def _coerce_uuid(value, key: str) -> uuid.UUID:
        try:
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise InvalidWorkflowEventPayload(f"{key} must be a UUID") from exc

    @staticmethod
    def _require_run_state(run: ContentProductionRun, *states: WorkflowState) -> None:
        allowed = {state.value for state in states}
        if run.state not in allowed:
            expected = ", ".join(sorted(allowed))
            raise InvalidWorkflowTransition(f"run state {run.state} is invalid; expected one of: {expected}")

    @staticmethod
    def _require_artifact_run(artifact, run: ContentProductionRun) -> None:
        if artifact.production_run_id != run.id:
            raise InvalidWorkflowEventPayload("artifact does not belong to the event production run")


def build_core_event_dispatcher(session, **options) -> EventDispatcher:
    handlers = CoreWorkflowEventHandlers(session, **options)
    tracing = WorkflowTraceService(session)
    dispatcher = EventDispatcher()
    registrations = {
        WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED: (
            handlers.content_production_request_created,
            "content_production_request_handling",
            "ContentProductionRepository",
            (),
        ),
        WorkflowEventType.CANDIDATE_SELECTION_REQUESTED: (
            handlers.candidate_selection_requested,
            "candidate_selection",
            "CandidateSelectionService",
            (),
        ),
        WorkflowEventType.CANDIDATE_SHORTLIST_PREPARED: (
            handlers.candidate_shortlist_prepared,
            "shortlist_preparation",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVAL_REQUESTED: (
            handlers.candidate_shortlist_approval_requested,
            "shortlist_approval_gate",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED: (
            handlers.candidate_shortlist_approved,
            "shortlist_approval_event_progression",
            "ContentProductionRepository",
            (),
        ),
        WorkflowEventType.CANDIDATE_SHORTLIST_REJECTED: (
            handlers.candidate_shortlist_rejected,
            "shortlist_rejection_event_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED: (
            handlers.content_sufficiency_check_requested,
            "content_sufficiency",
            "ContentSufficiencyService",
            (),
        ),
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED: (
            handlers.content_sufficiency_checked,
            "sufficiency_result_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED: (
            handlers.article_extraction_requested,
            "article_extraction",
            "ArticleExtractionService",
            (),
        ),
        WorkflowEventType.ARTICLE_EXTRACTED: (
            handlers.article_extracted,
            "article_extraction_completion",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.ARTICLE_EXTRACTION_FAILED: (
            handlers.article_extraction_failed,
            "article_extraction_failure_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.WEB_ENRICHMENT_REQUESTED: (
            handlers.web_enrichment_requested,
            "web_enrichment",
            "WebEnrichmentService",
            (),
        ),
        WorkflowEventType.WEB_ENRICHED: (
            handlers.web_enriched,
            "web_enrichment_completion",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.WEB_ENRICHMENT_FAILED: (
            handlers.web_enrichment_failed,
            "web_enrichment_failure_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.EDITORIAL_BRIEF_REQUESTED: (
            handlers.editorial_brief_requested,
            "editorial_brief_creation",
            "EditorialBriefService",
            (),
        ),
        WorkflowEventType.EDITORIAL_BRIEF_CREATED: (
            handlers.editorial_brief_created,
            "editorial_brief_completion",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.DRAFT_GENERATION_REQUESTED: (
            handlers.draft_generation_requested,
            "telegram_draft_generation",
            "TelegramDraftService",
            (),
        ),
        WorkflowEventType.DRAFT_GENERATED: (
            handlers.draft_generated,
            "draft_generation_completion",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.DRAFT_QUALITY_CHECK_REQUESTED: (
            handlers.draft_quality_check_requested,
            "draft_quality_check",
            "DraftQualityService",
            (),
        ),
        WorkflowEventType.DRAFT_QUALITY_CHECKED: (
            handlers.draft_quality_checked,
            "draft_quality_result_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.DRAFT_REVISION_REQUESTED: (
            handlers.draft_revision_requested,
            "draft_revision_pause",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.MEDIA_RESOLUTION_REQUESTED: (
            handlers.media_resolution_requested,
            "media_resolution",
            "MediaResolverService",
            (),
        ),
        WorkflowEventType.MEDIA_SELECTED: (
            handlers.media_selected,
            "media_selection_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.IMAGE_GENERATION_REQUESTED: (
            handlers.image_generation_requested,
            "image_generation_request_creation",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.IMAGE_GENERATED: (
            handlers.image_generated,
            "image_generation_callback_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.IMAGE_GENERATION_FAILED: (
            handlers.image_generation_failed,
            "image_generation_failure_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED: (
            handlers.telegram_package_requested,
            "telegram_package_creation",
            "TelegramPackageService",
            (),
        ),
        WorkflowEventType.TELEGRAM_PACKAGE_READY: (
            handlers.telegram_package_ready,
            "telegram_package_ready_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.FINAL_APPROVAL_REQUESTED: (
            handlers.final_approval_requested,
            "final_approval_gate",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.POST_PACKAGE_APPROVED: (
            handlers.post_package_approved,
            "final_approval_dispatch_progression",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.POST_PACKAGE_REJECTED: (
            handlers.post_package_rejected,
            "final_rejection_event_validation",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED: (
            handlers.telegram_dispatch_requested,
            "dispatch_handoff",
            "TelegramDispatchService",
            (),
        ),
        WorkflowEventType.TELEGRAM_POST_PUBLISHED: (
            handlers.telegram_post_published,
            "telegram_success_callback_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.TELEGRAM_POST_FAILED: (
            handlers.telegram_post_failed,
            "telegram_failure_callback_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
        WorkflowEventType.PRODUCTION_RUN_FAILED: (
            handlers.production_run_failed,
            "production_run_failure_handling",
            "CoreWorkflowEventHandlers",
            (),
        ),
    }
    for event_type, (handler, step_name, service_name, additional_steps) in registrations.items():
        dispatcher.register(
            event_type,
            tracing.wrap(
                handler,
                step_name=step_name,
                service_name=service_name,
                additional_steps=additional_steps,
            ),
        )
    return dispatcher
