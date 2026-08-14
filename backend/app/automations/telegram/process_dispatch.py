from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.decisions import (
    evaluate_review_policy,
)
from app.automations.telegram.handler_contracts import (
    ProcessDispatchPayload,
    _parse_payload,
    _redacted_dict,
    _redacted_list,
    build_evidence_map,
    generation_input_hash,
    sha256_canonical,
)
from app.automations.telegram.policy import evaluate_auto_publish
from app.automations.telegram.process_support import (
    _content_pack_and_variant,
    _exact_dispatch_evidence,
    _generation_error,
    _route_parent_revision,
    dispatch_media,
    enqueue_telegram_publish_intent,
    media_decision,
    require_automation_variant_write_allowed,
    resolve_process_prompt,
)
from app.automations.telegram.route_policy import retry_at
from app.core.faults import FaultInjector
from app.core.redaction import redact_string
from app.db.models import SourceItem
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    GenerationAttempt,
    GenerationRun,
    PlatformVariantRevision,
)
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.telegram_schema import (
    TelegramRewriteInput,
    TelegramRewriteOutput,
    TelegramVariantContent,
)
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent
from app.jobs.registry import JobContext
from app.jobs.types import JobExecution, job_payload_copy
from app.publishing.models import Destination
from app.stories.models import StoryRevision
from app.workflows.states import require_generation_run_transition

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TelegramProcessDependencies:
    profile_resolver: Any
    fault_injector: FaultInjector


@dataclass(frozen=True, slots=True)
class _GenerationPhase:
    session: Any
    job: JobExecution
    payload: ProcessDispatchPayload
    workflow_job_id: UUID
    route: AutomationRoute
    provider: Any
    provider_request: GenerationProviderRequest
    active_attempt_id: UUID
    dependencies: TelegramProcessDependencies


async def _invoke_and_persist_generation(phase: _GenerationPhase) -> dict[str, Any] | None:
    """Call the provider outside a transaction, then durably classify the result."""

    try:
        generated = await phase.provider.generate(phase.provider_request)
        await phase.dependencies.fault_injector.hit(
            "telegram_process.after_provider_before_persist",
            {
                "workflow_job_id": str(phase.workflow_job_id),
                "dispatch_id": str(phase.payload.dispatch_id),
                "generation_attempt_id": str(phase.active_attempt_id),
            },
        )
        parsed_output = TelegramRewriteOutput.model_validate(generated.output).model_dump(mode="json")
        durable_output = _redacted_dict(
            {
                "provider": generated.provider,
                "requested_model": generated.requested_model,
                "resolved_model": generated.resolved_model,
                "output": parsed_output,
                "raw_text": generated.raw_text,
                "usage": generated.usage,
                "finish_reason": generated.finish_reason,
            }
        )
    except Exception as exc:
        async with phase.session.begin():
            current_dispatch = await phase.session.scalar(
                select(AutomationDispatch)
                .where(AutomationDispatch.id == phase.payload.dispatch_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            current_run = (
                await phase.session.scalar(
                    select(GenerationRun)
                    .where(GenerationRun.id == current_dispatch.generation_run_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if current_dispatch is not None and current_dispatch.generation_run_id
                else None
            )
            current_attempt = await phase.session.scalar(
                select(GenerationAttempt)
                .where(GenerationAttempt.id == phase.active_attempt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            mapped = _generation_error(exc, phase.route, phase.job)
            if current_dispatch is not None and current_run is not None and current_attempt is not None:
                if current_dispatch.variant_revision_id is not None or (
                    (current_run.request_payload or {}).get("execution") or {}
                ).get("active_generation_attempt_id") != str(phase.active_attempt_id):
                    return {
                        "dispatch_id": str(phase.payload.dispatch_id),
                        "generation_run_id": str(current_run.id),
                        "superseded": True,
                    }
                error_class = (
                    "retryable"
                    if isinstance(mapped, RetryableJobError)
                    else "needs_review"
                    if isinstance(mapped, NeedsReviewJobError)
                    else "permanent"
                )
                durable_error_code = redact_string(str(getattr(mapped, "code", "generation_failed")))
                durable_error_message = redact_string(str(mapped))
                current_attempt.status = "failed"
                current_attempt.error_class = error_class
                current_attempt.error_code = durable_error_code
                current_attempt.error_message = durable_error_message
                if isinstance(exc, ValidationError):
                    current_attempt.validation_errors = _redacted_list(
                        [
                            {
                                "type": item["type"],
                                "loc": [str(part) for part in item["loc"]],
                                "message": item["msg"],
                            }
                            for item in exc.errors(
                                include_input=False,
                                include_url=False,
                            )
                        ]
                    )
                current_attempt.finished_at = datetime.now(UTC)
                current_run.status = require_generation_run_transition(current_run.status, "failed")
                current_run.error_class = error_class
                current_run.error_code = durable_error_code
                current_run.error_message = durable_error_message
                current_run.finished_at = datetime.now(UTC)
                current_dispatch.status = "needs_review" if error_class == "needs_review" else "failed"
        if mapped is exc:
            raise
        raise mapped from None

    async with phase.session.begin():
        current_run = await phase.session.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == phase.provider_request.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current_attempt = await phase.session.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.id == phase.active_attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current_run is None or current_attempt is None:
            raise RetryableJobError(
                code="generation_attempt_missing",
                message="Generation attempt disappeared before persistence",
            )
        if ((current_run.request_payload or {}).get("execution") or {}).get("active_generation_attempt_id") != str(
            phase.active_attempt_id
        ):
            return {
                "dispatch_id": str(phase.payload.dispatch_id),
                "generation_run_id": str(current_run.id),
                "superseded": True,
            }
        current_attempt.response_payload = _redacted_dict(durable_output)
        current_attempt.resolved_model = durable_output["resolved_model"]
        current_attempt.usage = _redacted_dict(durable_output["usage"])
        current_attempt.validation_errors = []
        current_attempt.status = "completed"
        current_attempt.finished_at = datetime.now(UTC)
        current_run.output_payload = _redacted_dict(durable_output)
        current_run.status = require_generation_run_transition(current_run.status, "completed")
        current_run.finished_at = datetime.now(UTC)
        current_run.error_class = None
        current_run.error_code = None
        current_run.error_message = None
        phase.session.add(
            WorkflowEvent(
                workflow_job_id=phase.workflow_job_id,
                event_type="telegram.generation.completed",
                actor="automation",
                event_data=redact_event_data(
                    {
                        "dispatch_id": str(phase.payload.dispatch_id),
                        "generation_run_id": str(current_run.id),
                        "generation_attempt_id": str(current_attempt.id),
                        "resolved_model": current_attempt.resolved_model,
                        "usage": current_attempt.usage,
                    }
                ),
            )
        )
    return None


@dataclass(frozen=True, slots=True)
class _RevisionPhase:
    session: Any
    payload: ProcessDispatchPayload
    workflow_job_id: UUID
    workflow_attempt_count: int


async def _persist_revision_and_publish(phase: _RevisionPhase) -> dict[str, Any]:
    """Arbitrate lineage, persist the immutable revision, and enqueue its publish intent."""

    session = phase.session
    payload = phase.payload
    workflow_job_id = phase.workflow_job_id
    workflow_attempt_count = phase.workflow_attempt_count
    async with session.begin():
        session.expire_all()
        dispatch = await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.id == payload.dispatch_id)
            .execution_options(populate_existing=True)
        )
        if dispatch is None:
            raise PermanentJobError(
                code="telegram_dispatch_missing",
                message="Telegram automation dispatch was not found",
            )
        if dispatch.variant_revision_id is not None:
            return {
                "dispatch_id": str(dispatch.id),
                "revision_id": str(dispatch.variant_revision_id),
                "publish_job_id": str(dispatch.publish_job_id) if dispatch.publish_job_id else None,
                "idempotent": True,
            }
        run = await session.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == dispatch.generation_run_id)
            .execution_options(populate_existing=True)
        )
        if run is None or run.status != "completed" or not run.output_payload:
            raise RetryableJobError(
                code="generation_output_not_durable",
                message="Generation output is not yet durable",
            )
        attempt = await session.scalar(
            select(GenerationAttempt)
            .where(
                GenerationAttempt.generation_run_id == run.id,
                GenerationAttempt.status == "completed",
            )
            .order_by(GenerationAttempt.attempt_number.desc())
            .limit(1)
        )
        if attempt is None:
            raise RetryableJobError(
                code="generation_attempt_not_durable",
                message="Generation attempt is not yet durable",
            )
        route = await session.scalar(
            select(AutomationRoute)
            .where(AutomationRoute.id == dispatch.route_id)
            .execution_options(populate_existing=True)
        )
        story_revision = await session.get(StoryRevision, dispatch.story_revision_id)
        source_item = await session.get(SourceItem, dispatch.source_item_id)
        if route is None or story_revision is None or source_item is None:
            raise PermanentJobError(
                code="telegram_dispatch_context_missing",
                message="Telegram dispatch context is incomplete",
            )
        provisional_dispatch_identity = (
            dispatch.route_id,
            dispatch.story_revision_id,
            dispatch.source_item_id,
            dispatch.generation_run_id,
            dispatch.creation_sequence,
            dispatch.dispatch_kind,
        )
        provisional_route_brand_profile_id = route.brand_profile_id
        unresolved_earlier = await session.scalar(
            select(AutomationDispatch)
            .join(StoryRevision, StoryRevision.id == AutomationDispatch.story_revision_id)
            .where(
                AutomationDispatch.route_id == dispatch.route_id,
                AutomationDispatch.id != dispatch.id,
                AutomationDispatch.creation_sequence < dispatch.creation_sequence,
                AutomationDispatch.variant_revision_id.is_(None),
                AutomationDispatch.status.in_(("captured", "researching", "generating", "retryable")),
                StoryRevision.story_id == story_revision.story_id,
            )
            .order_by(AutomationDispatch.creation_sequence)
            .limit(1)
        )
        if unresolved_earlier is not None:
            scheduled = retry_at(
                route.retry_policy or {},
                attempt_number=max(1, workflow_attempt_count),
                now=datetime.now(UTC),
            )
            if scheduled is None:
                raise NeedsReviewJobError(
                    code="telegram_route_lineage_blocked",
                    message="An earlier route dispatch requires operator attention",
                )
            raise RetryableJobError(
                code="telegram_route_lineage_waiting",
                message="Waiting for an earlier route dispatch revision",
                retry_at=scheduled,
            )
        parent = await _route_parent_revision(
            session,
            dispatch=dispatch,
            story_id=story_revision.story_id,
        )
        _, variant = await _content_pack_and_variant(
            session,
            dispatch=dispatch,
            route=route,
            story_revision=story_revision,
            parent=parent,
        )
        locked_dispatch = await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.id == payload.dispatch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_dispatch is None:
            raise PermanentJobError(
                code="telegram_dispatch_missing",
                message="Telegram automation dispatch was not found",
            )
        if locked_dispatch.variant_revision_id is not None:
            return {
                "dispatch_id": str(locked_dispatch.id),
                "revision_id": str(locked_dispatch.variant_revision_id),
                "publish_job_id": (str(locked_dispatch.publish_job_id) if locked_dispatch.publish_job_id else None),
                "idempotent": True,
            }
        if (
            locked_dispatch.route_id,
            locked_dispatch.story_revision_id,
            locked_dispatch.source_item_id,
            locked_dispatch.generation_run_id,
            locked_dispatch.creation_sequence,
            locked_dispatch.dispatch_kind,
        ) != provisional_dispatch_identity:
            raise NeedsReviewJobError(
                code="telegram_dispatch_identity_drift",
                message="Telegram dispatch identity changed before revision persistence",
            )
        dispatch = locked_dispatch
        locked_route = await session.scalar(
            select(AutomationRoute)
            .where(AutomationRoute.id == dispatch.route_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_route is None:
            raise PermanentJobError(
                code="telegram_route_missing",
                message="Telegram automation route was not found",
            )
        if locked_route.brand_profile_id != provisional_route_brand_profile_id:
            raise NeedsReviewJobError(
                code="telegram_route_identity_drift",
                message="Telegram route identity changed before revision persistence",
            )
        route = locked_route
        refreshed_parent = await _route_parent_revision(
            session,
            dispatch=dispatch,
            story_id=story_revision.story_id,
        )
        if refreshed_parent is not None and refreshed_parent.platform_variant_id != variant.id:
            raise RetryableJobError(
                code="telegram_route_lineage_changed",
                message="Telegram route lineage changed before revision persistence",
            )
        if refreshed_parent is None and parent is not None:
            raise NeedsReviewJobError(
                code="telegram_route_lineage_invalid",
                message="Telegram route lineage disappeared before revision persistence",
            )
        parent = refreshed_parent
        control = await session.scalar(
            select(AutomationControl)
            .where(AutomationControl.id == "global")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        destination = await session.scalar(
            select(Destination)
            .where(Destination.id == route.destination_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if destination is None:
            raise PermanentJobError(
                code="telegram_destination_missing",
                message="Telegram destination was not found",
            )
        snapshot = await _exact_dispatch_evidence(session, story_revision.id)
        evidence_map = build_evidence_map(snapshot)
        content_item, media = await dispatch_media(session, source_item)
        media_ids, media_ready, media_reason = media_decision(route, media)
        output = TelegramRewriteOutput.model_validate(run.output_payload["output"])
        content = TelegramVariantContent.model_validate(
            {
                "body": output.body,
                "parse_mode": output.parse_mode,
                "buttons": output.buttons,
                "source_item_id": dispatch.source_item_id,
                "source_url": source_item.source_url,
                "media_policy": route.media_policy,
                "media_asset_ids": media_ids if route.media_policy == "preserve" else [],
                "direction": content_item.direction or "ltr",
                "dry_run": dispatch.dispatch_kind == "dry_run",
            }
        ).model_dump(mode="json")
        validation_results = [
            {"gate": "telegram_schema", "ok": True, "reason": None},
            {"gate": "evidence", "ok": True, "reason": None},
            {"gate": "media", "ok": media_ready, "reason": media_reason},
        ]
        await require_automation_variant_write_allowed(session, variant.id)
        revision_number = (
            int(
                await session.scalar(
                    select(func.coalesce(func.max(PlatformVariantRevision.revision_number), 0)).where(
                        PlatformVariantRevision.platform_variant_id == variant.id
                    )
                )
                or 0
            )
            + 1
        )
        gate = evaluate_auto_publish(
            global_pause=bool(control and control.global_pause),
            global_dry_run=bool(control and control.dry_run),
            route_paused=route.paused_at is not None,
            destination_enabled=destination.enabled,
            destination_health=destination.health_status,
            validation_ok=True,
            evidence_ready=True,
            media_ready=media_ready,
        )
        review = evaluate_review_policy(
            publishing_policy=route.publishing_policy,
            explicit_force_review=payload.force_review,
            dispatch_kind=dispatch.dispatch_kind,
            media_policy=route.media_policy,
            auto_publish_allowed=gate.allowed,
            auto_publish_reason=gate.reason,
        )
        revision = PlatformVariantRevision(
            platform_variant_id=variant.id,
            parent_revision_id=parent.id if parent is not None else None,
            generation_attempt_id=attempt.id,
            revision_number=revision_number,
            content=content,
            content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
            evidence_map=evidence_map,
            validation_results=validation_results,
            approval_state="approved" if review.approved else "pending_review",
            approval_note=review.note,
            approved_at=datetime.now(UTC) if review.approved else None,
            created_by=f"automation:{route.id}",
        )
        session.add(revision)
        await session.flush()
        dispatch.variant_revision_id = revision.id
        dispatch.status = "approved" if review.approved else "pending_review"
        dispatch.error_code = None
        dispatch.error_message = None
        publish_job = None
        if review.approved:
            publish_job = await enqueue_telegram_publish_intent(
                session,
                revision=revision,
                destination=destination,
                dispatch=dispatch,
            )
        session.add(
            WorkflowEvent(
                workflow_job_id=workflow_job_id,
                event_type=(
                    "telegram.revision.auto_approved" if review.approved else "telegram.revision.review_required"
                ),
                actor="automation",
                event_data=redact_event_data(
                    {
                        "route_id": str(route.id),
                        "dispatch_id": str(dispatch.id),
                        "revision_id": str(revision.id),
                        "content_hash": revision.content_hash,
                        "reason": None if review.approved else revision.approval_note,
                    }
                ),
            )
        )
        if dispatch.dispatch_kind == "source_edit":
            session.add(
                WorkflowEvent(
                    workflow_job_id=workflow_job_id,
                    event_type="telegram.source_edit.revision_created",
                    actor="automation",
                    event_data=redact_event_data(
                        {
                            "route_id": str(route.id),
                            "dispatch_id": str(dispatch.id),
                            "revision_id": str(revision.id),
                            "parent_revision_id": (
                                str(revision.parent_revision_id) if revision.parent_revision_id else None
                            ),
                        }
                    ),
                )
            )
        await session.flush()
        return {
            "dispatch_id": str(dispatch.id),
            "generation_run_id": str(run.id),
            "revision_id": str(revision.id),
            "review_required": not review.approved,
            "publish_job_id": str(publish_job.id) if publish_job is not None else None,
        }


async def _process_route_dispatch(
    job: JobExecution,
    context: JobContext,
    *,
    dependencies: TelegramProcessDependencies,
) -> dict[str, Any]:
    payload = _parse_payload(ProcessDispatchPayload, job_payload_copy(job))
    workflow_job_id = job.id
    workflow_attempt_count = job.attempt_count
    session = context.session
    provider = None
    provider_request = None
    active_attempt_id: UUID | None = None
    durable_output: dict[str, Any] | None = None

    async with session.begin():
        dispatch = await session.scalar(
            select(AutomationDispatch).where(AutomationDispatch.id == payload.dispatch_id).with_for_update()
        )
        if dispatch is None:
            raise PermanentJobError(
                code="telegram_dispatch_missing",
                message="Telegram automation dispatch was not found",
            )
        if dispatch.variant_revision_id is not None:
            return {
                "dispatch_id": str(dispatch.id),
                "revision_id": str(dispatch.variant_revision_id),
                "publish_job_id": str(dispatch.publish_job_id) if dispatch.publish_job_id else None,
                "idempotent": True,
            }
        route = await session.get(AutomationRoute, dispatch.route_id)
        story_revision = await session.get(StoryRevision, dispatch.story_revision_id)
        source_item = await session.get(SourceItem, dispatch.source_item_id)
        if route is None or story_revision is None or source_item is None:
            raise PermanentJobError(
                code="telegram_dispatch_context_missing",
                message="Telegram dispatch context is incomplete",
            )
        if payload.completed_research_run_id is not None:
            from app.research.models import ResearchRun

            completed_run = await session.get(ResearchRun, payload.completed_research_run_id)
            if (
                completed_run is None
                or completed_run.status != "succeeded"
                or completed_run.story_id != story_revision.story_id
                or completed_run.result_story_revision_id != story_revision.id
            ):
                raise NeedsReviewJobError(
                    code="telegram_research_continuation_invalid",
                    message="Completed research continuation is invalid",
                )
        if payload.completed_research_run_id is None and route.research_mode == "manual":
            from app.research.models import ResearchRun

            profile_value = (route.content_filters or {}).get("research_provider_profile_id")
            try:
                research_profile_id = UUID(str(profile_value))
            except TypeError, ValueError:
                raise PermanentJobError(
                    code="telegram_research_profile_invalid",
                    message="Telegram research provider profile is invalid",
                ) from None
            manual_run = await session.scalar(
                select(ResearchRun)
                .where(
                    ResearchRun.story_id == story_revision.story_id,
                    ResearchRun.provider_profile_id == research_profile_id,
                    ResearchRun.requested_mode == "manual",
                    ResearchRun.status == "succeeded",
                    ResearchRun.result_story_revision_id.is_not(None),
                    ResearchRun.created_at >= dispatch.created_at,
                )
                .order_by(ResearchRun.finished_at.desc(), ResearchRun.id.desc())
                .limit(1)
            )
            if manual_run is None:
                dispatch.status = "needs_review"
                dispatch.error_code = "telegram_manual_research_required"
                dispatch.error_message = "Manual research is required before generation"
                session.add(
                    WorkflowEvent(
                        workflow_job_id=job.id,
                        event_type="telegram.research.review_required",
                        actor="automation",
                        event_data=redact_event_data(
                            {
                                "dispatch_id": str(dispatch.id),
                                "story_id": str(story_revision.story_id),
                            }
                        ),
                    )
                )
                raise NeedsReviewJobError(
                    code="telegram_manual_research_required",
                    message="Manual research is required before generation",
                )
            selected_revision = await session.get(StoryRevision, manual_run.result_story_revision_id)
            if selected_revision is None or selected_revision.story_id != story_revision.story_id:
                raise NeedsReviewJobError(
                    code="telegram_manual_research_result_invalid",
                    message="Manual research result revision is invalid",
                )
            dispatch.story_revision_id = selected_revision.id
            dispatch.status = "captured"
            dispatch.error_code = None
            dispatch.error_message = None
            story_revision = selected_revision
        prompt = await resolve_process_prompt(
            session,
            route=route,
            payload=payload,
            workflow_job_id=workflow_job_id,
        )
        if payload.completed_research_run_id is None and route.research_mode == "auto_if_incomplete":
            from app.research.service import ResearchRequestError, ResearchService

            profile_value = (route.content_filters or {}).get("research_provider_profile_id")
            try:
                profile_id = UUID(str(profile_value))
            except TypeError, ValueError:
                raise PermanentJobError(
                    code="telegram_research_profile_invalid",
                    message="Telegram research provider profile is invalid",
                ) from None
            continuation = {
                "job_type": "telegram.route.process",
                "payload": {
                    "dispatch_id": str(dispatch.id),
                    "force_review": payload.force_review,
                    "prompt_template_version_id": str(prompt.id),
                    "prompt_checksum": prompt.checksum_sha256,
                },
                "idempotency_prefix": (f"telegram-route-process-after-research:{dispatch.id}"),
                "subscriber_id": f"telegram-dispatch:{dispatch.id}",
                "expected_route_id": str(route.id),
                "expected_story_id": str(story_revision.story_id),
                "expected_story_revision_id": str(story_revision.id),
                "expected_provider_profile_id": str(profile_id),
                "expected_research_mode": "auto_if_incomplete",
            }
            try:
                research = await ResearchService(session).request(
                    story_id=story_revision.story_id,
                    mode="auto_if_incomplete",
                    depth="standard",
                    provider_profile_id=profile_id,
                    query_hint=None,
                    continuation=continuation,
                )
            except ResearchRequestError as exc:
                raise PermanentJobError(
                    code="telegram_research_request_invalid",
                    message=str(exc),
                ) from None
            if research.disposition == "enqueued":
                dispatch.status = "researching"
                dispatch.error_code = None
                dispatch.error_message = None
                return {
                    "dispatch_id": str(dispatch.id),
                    "research_run_id": str(research.run_id),
                    "research_job_id": str(research.job_id),
                }
        snapshot = await _exact_dispatch_evidence(session, story_revision.id)
        content_item, media = await dispatch_media(
            session,
            source_item,
            lock_for_revision=False,
        )
        brand = await session.get(BrandProfile, route.brand_profile_id)
        profile = await session.get(AIProviderProfile, route.ai_provider_profile_id)
        destination = await session.get(Destination, route.destination_id)
        if prompt is None or brand is None or profile is None or destination is None:
            raise PermanentJobError(
                code="telegram_route_configuration_missing",
                message="Telegram route configuration is incomplete",
            )

        run = (
            await session.get(GenerationRun, dispatch.generation_run_id)
            if dispatch.generation_run_id is not None
            else None
        )
        if run is not None and run.status == "completed" and run.output_payload:
            if generation_input_hash(dict(run.request_payload or {})) != run.input_hash:
                raise NeedsReviewJobError(
                    code="telegram_generation_input_drift",
                    message="Durable generation input no longer matches its hash",
                )
            durable_output = dict(run.output_payload)
        else:
            if run is not None and run.status == "running":
                active_claim = int(
                    ((run.request_payload or {}).get("execution") or {}).get("active_workflow_attempt", 0)
                )
                if active_claim == workflow_attempt_count:
                    return {
                        "dispatch_id": str(dispatch.id),
                        "generation_run_id": str(run.id),
                        "already_in_progress": True,
                    }
                attempts = list(
                    await session.scalars(
                        select(GenerationAttempt)
                        .where(GenerationAttempt.generation_run_id == run.id)
                        .order_by(GenerationAttempt.attempt_number)
                        .with_for_update()
                    )
                )
                for stale in attempts:
                    if stale.status == "running":
                        stale.status = "failed"
                        stale.error_class = "retryable"
                        stale.error_code = "stale_generation_attempt"
                        stale.error_message = "Generation attempt lease was superseded"
                        stale.finished_at = datetime.now(UTC)
            else:
                attempts = (
                    list(
                        await session.scalars(
                            select(GenerationAttempt)
                            .where(GenerationAttempt.generation_run_id == run.id)
                            .order_by(GenerationAttempt.attempt_number)
                            .with_for_update()
                        )
                    )
                    if run is not None
                    else []
                )

            model_override = (route.content_filters or {}).get("model")
            try:
                resolved = await dependencies.profile_resolver.resolve(profile, model_override)
            except Exception as exc:
                mapped = _generation_error(exc, route, job)
                if mapped is exc:
                    raise
                raise mapped from None
            rewrite_input = TelegramRewriteInput.model_validate(
                {
                    "source_text": snapshot.content_text,
                    "source_url": snapshot.source_url,
                    "source_channel": source_item.external_id_norm or str(route.source_id),
                    "language": brand.output_language,
                    "direction": content_item.direction or "ltr",
                    "attribution_policy": route.attribution_policy,
                    "custom_footer": route.custom_footer,
                }
            )
            values = rewrite_input.model_dump(mode="json")
            try:
                rendered_user = prompt.user_template.format(**values)
            except KeyError, ValueError:
                raise PermanentJobError(
                    code="telegram_prompt_invalid",
                    message="Telegram prompt template cannot be rendered",
                ) from None
            requested_model = model_override or profile.default_model
            semantic_request = {
                "dispatch_id": str(dispatch.id),
                "route_id": str(route.id),
                "story_revision_id": str(story_revision.id),
                "evidence_snapshot_id": str(snapshot.id),
                "prompt_template_version_id": str(prompt.id),
                "prompt_checksum": prompt.checksum_sha256,
                "provider_profile_id": str(profile.id),
                "requested_model": requested_model,
                "selected_model": resolved.model,
            }
            request_payload = _redacted_dict(
                {
                    "semantic": semantic_request,
                    "input": values,
                    "execution": {
                        "active_workflow_job_id": str(workflow_job_id),
                        "active_workflow_attempt": workflow_attempt_count,
                    },
                }
            )
            computed_input_hash = generation_input_hash(request_payload)
            if computed_input_hash is None:  # pragma: no cover - constructed above
                raise RuntimeError("Generation input hash could not be computed")
            if run is None:
                run = GenerationRun(
                    story_revision_id=story_revision.id,
                    provider_profile_id=profile.id,
                    prompt_template_version_id=prompt.id,
                    requested_model=(redact_string(requested_model) if requested_model is not None else None),
                    status="running",
                    input_hash=computed_input_hash,
                    request_payload=request_payload,
                    output_payload={},
                    started_at=datetime.now(UTC),
                )
                session.add(run)
                await session.flush()
                dispatch.generation_run_id = run.id
            else:
                existing_hash = generation_input_hash(dict(run.request_payload or {}))
                if existing_hash != run.input_hash or computed_input_hash != run.input_hash:
                    raise NeedsReviewJobError(
                        code="telegram_generation_input_drift",
                        message="Generation retry input differs from the durable request",
                    )
                run.status = require_generation_run_transition(run.status, "running")
                run.error_class = None
                run.error_code = None
                run.error_message = None
                run.finished_at = None
                if run.requested_model is not None:
                    run.requested_model = redact_string(run.requested_model)
                run.request_payload = request_payload
            dispatch.status = "generating"
            dispatch.error_code = None
            dispatch.error_message = None
            created_attempt = GenerationAttempt(
                generation_run_id=run.id,
                attempt_number=max((item.attempt_number for item in attempts), default=0) + 1,
                provider=resolved.provider_type,
                requested_model=(redact_string(requested_model) if requested_model is not None else None),
                prompt_snapshot=_redacted_dict(
                    {
                        "system": prompt.system_template,
                        "user": rendered_user,
                        "schema": prompt.output_schema,
                    }
                ),
                response_payload={},
                usage={},
                validation_errors=[],
                status="running",
                started_at=datetime.now(UTC),
            )
            session.add(created_attempt)
            await session.flush()
            run.request_payload = _redacted_dict(
                {
                    **request_payload,
                    "execution": {
                        **request_payload["execution"],
                        "active_generation_attempt_id": str(created_attempt.id),
                    },
                }
            )
            active_attempt_id = created_attempt.id
            provider = resolved.provider
            provider_request = GenerationProviderRequest(
                run_id=run.id,
                purpose="telegram_rewrite",
                requested_model=resolved.model,
                messages=(
                    ProviderMessage(role="system", content=prompt.system_template),
                    ProviderMessage(role="user", content=rendered_user),
                ),
                response_schema=dict(prompt.output_schema or {}),
                metadata={
                    "dispatch_id": str(dispatch.id),
                    "route_id": str(route.id),
                    "evidence_snapshot_id": str(snapshot.id),
                    "provider_profile_id": str(profile.id),
                },
            )

    if durable_output is None:
        if provider is None or provider_request is None or active_attempt_id is None:
            raise RuntimeError("Telegram generation attempt was not prepared")
        short_circuit = await _invoke_and_persist_generation(
            _GenerationPhase(
                session=session,
                job=job,
                payload=payload,
                workflow_job_id=workflow_job_id,
                route=route,
                provider=provider,
                provider_request=provider_request,
                active_attempt_id=active_attempt_id,
                dependencies=dependencies,
            )
        )
        if short_circuit is not None:
            return short_circuit

    return await _persist_revision_and_publish(
        _RevisionPhase(
            session=session,
            payload=payload,
            workflow_job_id=workflow_job_id,
            workflow_attempt_count=workflow_attempt_count,
        )
    )
