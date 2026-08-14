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


async def _persist_generation_failure(
    phase: _GenerationPhase,
    exc: Exception,
) -> tuple[dict[str, Any] | None, Exception]:
    short_circuit: dict[str, Any] | None = None
    mapped = _generation_error(exc, phase.route, phase.job)
    async with phase.session.begin():
        dispatch = await phase.session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.id == phase.payload.dispatch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        run = (
            await phase.session.scalar(
                select(GenerationRun)
                .where(GenerationRun.id == dispatch.generation_run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if dispatch is not None and dispatch.generation_run_id
            else None
        )
        attempt = await phase.session.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.id == phase.active_attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if dispatch is not None and run is not None and attempt is not None:
            if dispatch.variant_revision_id is not None or (
                ((run.request_payload or {}).get("execution") or {}).get("active_generation_attempt_id")
                != str(phase.active_attempt_id)
            ):
                short_circuit = {
                    "dispatch_id": str(phase.payload.dispatch_id),
                    "generation_run_id": str(run.id),
                    "superseded": True,
                }
            else:
                _record_generation_failure(exc, mapped, dispatch, run, attempt)
    return short_circuit, mapped


def _record_generation_failure(
    exc: Exception,
    mapped: Exception,
    dispatch: Any,
    run: Any,
    attempt: Any,
) -> None:
    error_class = (
        "retryable"
        if isinstance(mapped, RetryableJobError)
        else "needs_review"
        if isinstance(mapped, NeedsReviewJobError)
        else "permanent"
    )
    error_code = redact_string(str(getattr(mapped, "code", "generation_failed")))
    error_message = redact_string(str(mapped))
    attempt.status = "failed"
    attempt.error_class = error_class
    attempt.error_code = error_code
    attempt.error_message = error_message
    if isinstance(exc, ValidationError):
        attempt.validation_errors = _redacted_list(
            [
                {"type": item["type"], "loc": [str(part) for part in item["loc"]], "message": item["msg"]}
                for item in exc.errors(include_input=False, include_url=False)
            ]
        )
    attempt.finished_at = datetime.now(UTC)
    run.status = require_generation_run_transition(run.status, "failed")
    run.error_class = error_class
    run.error_code = error_code
    run.error_message = error_message
    run.finished_at = datetime.now(UTC)
    dispatch.status = "needs_review" if error_class == "needs_review" else "failed"


async def _persist_generation_success(
    phase: _GenerationPhase,
    durable_output: dict[str, Any],
) -> dict[str, Any] | None:
    async with phase.session.begin():
        run = await phase.session.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == phase.provider_request.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = await phase.session.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.id == phase.active_attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None or attempt is None:
            raise RetryableJobError(
                code="generation_attempt_missing",
                message="Generation attempt disappeared before persistence",
            )
        if ((run.request_payload or {}).get("execution") or {}).get("active_generation_attempt_id") != str(
            phase.active_attempt_id
        ):
            return {
                "dispatch_id": str(phase.payload.dispatch_id),
                "generation_run_id": str(run.id),
                "superseded": True,
            }
        attempt.response_payload = _redacted_dict(durable_output)
        attempt.resolved_model = durable_output["resolved_model"]
        attempt.usage = _redacted_dict(durable_output["usage"])
        attempt.validation_errors = []
        attempt.status = "completed"
        attempt.finished_at = datetime.now(UTC)
        run.output_payload = _redacted_dict(durable_output)
        run.status = require_generation_run_transition(run.status, "completed")
        run.finished_at = datetime.now(UTC)
        run.error_class = None
        run.error_code = None
        run.error_message = None
        phase.session.add(
            WorkflowEvent(
                workflow_job_id=phase.workflow_job_id,
                event_type="telegram.generation.completed",
                actor="automation",
                event_data=redact_event_data(
                    {
                        "dispatch_id": str(phase.payload.dispatch_id),
                        "generation_run_id": str(run.id),
                        "generation_attempt_id": str(attempt.id),
                        "resolved_model": attempt.resolved_model,
                        "usage": attempt.usage,
                    }
                ),
            )
        )
    return None


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
        short_circuit, mapped = await _persist_generation_failure(phase, exc)
        if short_circuit is not None:
            return short_circuit
        if mapped is exc:
            raise
        raise mapped from None
    return await _persist_generation_success(phase, durable_output)


@dataclass(frozen=True, slots=True)
class _RevisionPhase:
    session: Any
    payload: ProcessDispatchPayload
    workflow_job_id: UUID
    workflow_attempt_count: int


@dataclass(frozen=True, slots=True)
class _RevisionInputs:
    dispatch: Any
    run: Any
    attempt: Any
    route: Any
    story_revision: Any
    source_item: Any
    dispatch_identity: tuple[Any, ...]
    route_brand_profile_id: Any


def _dispatch_revision_result(dispatch: Any) -> dict[str, Any]:
    return {
        "dispatch_id": str(dispatch.id),
        "revision_id": str(dispatch.variant_revision_id),
        "publish_job_id": str(dispatch.publish_job_id) if dispatch.publish_job_id else None,
        "idempotent": True,
    }


async def _load_revision_inputs(phase: _RevisionPhase) -> _RevisionInputs | dict[str, Any]:
    session = phase.session
    dispatch = await session.scalar(
        select(AutomationDispatch)
        .where(AutomationDispatch.id == phase.payload.dispatch_id)
        .execution_options(populate_existing=True)
    )
    if dispatch is None:
        raise PermanentJobError(code="telegram_dispatch_missing", message="Telegram automation dispatch was not found")
    if dispatch.variant_revision_id is not None:
        return _dispatch_revision_result(dispatch)
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
        .where(GenerationAttempt.generation_run_id == run.id, GenerationAttempt.status == "completed")
        .order_by(GenerationAttempt.attempt_number.desc())
        .limit(1)
    )
    if attempt is None:
        raise RetryableJobError(
            code="generation_attempt_not_durable",
            message="Generation attempt is not yet durable",
        )
    route = await session.scalar(
        select(AutomationRoute).where(AutomationRoute.id == dispatch.route_id).execution_options(populate_existing=True)
    )
    story_revision = await session.get(StoryRevision, dispatch.story_revision_id)
    source_item = await session.get(SourceItem, dispatch.source_item_id)
    if route is None or story_revision is None or source_item is None:
        raise PermanentJobError(
            code="telegram_dispatch_context_missing",
            message="Telegram dispatch context is incomplete",
        )
    await _wait_for_earlier_revision(phase, dispatch, route, story_revision.story_id)
    identity = (
        dispatch.route_id,
        dispatch.story_revision_id,
        dispatch.source_item_id,
        dispatch.generation_run_id,
        dispatch.creation_sequence,
        dispatch.dispatch_kind,
    )
    return _RevisionInputs(
        dispatch,
        run,
        attempt,
        route,
        story_revision,
        source_item,
        identity,
        route.brand_profile_id,
    )


async def _wait_for_earlier_revision(
    phase: _RevisionPhase,
    dispatch: Any,
    route: Any,
    story_id: UUID,
) -> None:
    earlier = await phase.session.scalar(
        select(AutomationDispatch)
        .join(StoryRevision, StoryRevision.id == AutomationDispatch.story_revision_id)
        .where(
            AutomationDispatch.route_id == dispatch.route_id,
            AutomationDispatch.id != dispatch.id,
            AutomationDispatch.creation_sequence < dispatch.creation_sequence,
            AutomationDispatch.variant_revision_id.is_(None),
            AutomationDispatch.status.in_(("captured", "researching", "generating", "retryable")),
            StoryRevision.story_id == story_id,
        )
        .order_by(AutomationDispatch.creation_sequence)
        .limit(1)
    )
    if earlier is None:
        return
    scheduled = retry_at(
        route.retry_policy or {},
        attempt_number=max(1, phase.workflow_attempt_count),
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


def _validate_locked_dispatch(dispatch: Any, inputs: _RevisionInputs) -> dict[str, Any] | None:
    if dispatch is None:
        raise PermanentJobError(
            code="telegram_dispatch_missing",
            message="Telegram automation dispatch was not found",
        )
    if dispatch.variant_revision_id is not None:
        return _dispatch_revision_result(dispatch)
    identity = (
        dispatch.route_id,
        dispatch.story_revision_id,
        dispatch.source_item_id,
        dispatch.generation_run_id,
        dispatch.creation_sequence,
        dispatch.dispatch_kind,
    )
    if identity != inputs.dispatch_identity:
        raise NeedsReviewJobError(
            code="telegram_dispatch_identity_drift",
            message="Telegram dispatch identity changed before revision persistence",
        )
    return None


def _validate_locked_route(route: Any, inputs: _RevisionInputs) -> None:
    if route is None:
        raise PermanentJobError(
            code="telegram_route_missing",
            message="Telegram automation route was not found",
        )
    if route.brand_profile_id != inputs.route_brand_profile_id:
        raise NeedsReviewJobError(
            code="telegram_route_identity_drift",
            message="Telegram route identity changed before revision persistence",
        )


def _validate_refreshed_parent(refreshed_parent: Any, parent: Any, variant: Any) -> None:
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


async def _build_revision_artifacts(
    session: Any,
    inputs: _RevisionInputs,
    dispatch: Any,
    route: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], bool]:
    snapshot = await _exact_dispatch_evidence(session, inputs.story_revision.id)
    evidence_map = build_evidence_map(snapshot)
    content_item, media = await dispatch_media(session, inputs.source_item)
    media_ids, media_ready, media_reason = media_decision(route, media)
    output = TelegramRewriteOutput.model_validate(inputs.run.output_payload["output"])
    content = TelegramVariantContent.model_validate(
        {
            "body": output.body,
            "parse_mode": output.parse_mode,
            "buttons": output.buttons,
            "source_item_id": dispatch.source_item_id,
            "source_url": inputs.source_item.source_url,
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
    return evidence_map, content, validation_results, media_ready


async def _create_dispatch_revision(
    phase: _RevisionPhase,
    inputs: _RevisionInputs,
    dispatch: Any,
    route: Any,
    parent: Any,
    destination: Any,
    variant: Any,
    evidence_map: list[dict[str, Any]],
    content: dict[str, Any],
    validation_results: list[dict[str, Any]],
    gate: Any,
) -> tuple[Any, Any, Any]:
    session = phase.session
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
    review = evaluate_review_policy(
        publishing_policy=route.publishing_policy,
        explicit_force_review=phase.payload.force_review,
        dispatch_kind=dispatch.dispatch_kind,
        media_policy=route.media_policy,
        auto_publish_allowed=gate.allowed,
        auto_publish_reason=gate.reason,
    )
    revision = PlatformVariantRevision(
        platform_variant_id=variant.id,
        parent_revision_id=parent.id if parent is not None else None,
        generation_attempt_id=inputs.attempt.id,
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
    publish_job = (
        await enqueue_telegram_publish_intent(
            session,
            revision=revision,
            destination=destination,
            dispatch=dispatch,
        )
        if review.approved
        else None
    )
    return revision, review, publish_job


def _add_revision_events(
    session: Any,
    workflow_job_id: UUID,
    dispatch: Any,
    route: Any,
    revision: Any,
    review: Any,
) -> None:
    session.add(
        WorkflowEvent(
            workflow_job_id=workflow_job_id,
            event_type="telegram.revision.auto_approved" if review.approved else "telegram.revision.review_required",
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
                        "parent_revision_id": str(revision.parent_revision_id) if revision.parent_revision_id else None,
                    }
                ),
            )
        )


async def _persist_revision_and_publish(phase: _RevisionPhase) -> dict[str, Any]:
    """Arbitrate lineage, persist the immutable revision, and enqueue its publish intent."""

    session = phase.session
    async with session.begin():
        session.expire_all()
        inputs = await _load_revision_inputs(phase)
        if isinstance(inputs, dict):
            return inputs
        parent = await _route_parent_revision(
            session,
            dispatch=inputs.dispatch,
            story_id=inputs.story_revision.story_id,
        )
        _, variant = await _content_pack_and_variant(
            session,
            dispatch=inputs.dispatch,
            route=inputs.route,
            story_revision=inputs.story_revision,
            parent=parent,
        )
        locked_dispatch = await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.id == phase.payload.dispatch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        idempotent = _validate_locked_dispatch(locked_dispatch, inputs)
        if idempotent is not None:
            return idempotent
        dispatch = locked_dispatch
        locked_route = await session.scalar(
            select(AutomationRoute)
            .where(AutomationRoute.id == dispatch.route_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        _validate_locked_route(locked_route, inputs)
        route = locked_route
        refreshed_parent = await _route_parent_revision(
            session,
            dispatch=dispatch,
            story_id=inputs.story_revision.story_id,
        )
        _validate_refreshed_parent(refreshed_parent, parent, variant)
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
        evidence_map, content, validation_results, media_ready = await _build_revision_artifacts(
            session, inputs, dispatch, route
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
        revision, review, publish_job = await _create_dispatch_revision(
            phase,
            inputs,
            dispatch,
            route,
            parent,
            destination,
            variant,
            evidence_map,
            content,
            validation_results,
            gate,
        )
        _add_revision_events(
            session,
            phase.workflow_job_id,
            dispatch,
            route,
            revision,
            review,
        )
        await session.flush()
        return {
            "dispatch_id": str(dispatch.id),
            "generation_run_id": str(inputs.run.id),
            "revision_id": str(revision.id),
            "review_required": not review.approved,
            "publish_job_id": str(publish_job.id) if publish_job is not None else None,
        }


@dataclass(slots=True)
class _ProcessBase:
    dispatch: Any
    route: Any
    story_revision: Any
    source_item: Any


@dataclass(frozen=True, slots=True)
class _GenerationConfig:
    prompt: Any
    snapshot: Any
    content_item: Any
    brand: Any
    profile: Any


@dataclass(frozen=True, slots=True)
class _PreparedProcess:
    route: Any
    provider: Any | None = None
    provider_request: GenerationProviderRequest | None = None
    active_attempt_id: UUID | None = None
    durable_output: dict[str, Any] | None = None


async def _load_process_base(session: Any, payload: ProcessDispatchPayload) -> _ProcessBase | dict[str, Any]:
    dispatch = await session.scalar(
        select(AutomationDispatch).where(AutomationDispatch.id == payload.dispatch_id).with_for_update()
    )
    if dispatch is None:
        raise PermanentJobError(code="telegram_dispatch_missing", message="Telegram automation dispatch was not found")
    if dispatch.variant_revision_id is not None:
        return _dispatch_revision_result(dispatch)
    route = await session.get(AutomationRoute, dispatch.route_id)
    story_revision = await session.get(StoryRevision, dispatch.story_revision_id)
    source_item = await session.get(SourceItem, dispatch.source_item_id)
    if route is None or story_revision is None or source_item is None:
        raise PermanentJobError(
            code="telegram_dispatch_context_missing",
            message="Telegram dispatch context is incomplete",
        )
    return _ProcessBase(dispatch, route, story_revision, source_item)


def _research_profile_id(route: Any) -> UUID:
    value = (route.content_filters or {}).get("research_provider_profile_id")
    try:
        return UUID(str(value))
    except TypeError, ValueError:
        raise PermanentJobError(
            code="telegram_research_profile_invalid",
            message="Telegram research provider profile is invalid",
        ) from None


async def _validate_research_continuation(
    session: Any,
    payload: ProcessDispatchPayload,
    story_revision: Any,
) -> None:
    if payload.completed_research_run_id is None:
        return
    from app.research.models import ResearchRun

    completed = await session.get(ResearchRun, payload.completed_research_run_id)
    if (
        completed is None
        or completed.status != "succeeded"
        or completed.story_id != story_revision.story_id
        or completed.result_story_revision_id != story_revision.id
    ):
        raise NeedsReviewJobError(
            code="telegram_research_continuation_invalid",
            message="Completed research continuation is invalid",
        )


async def _apply_manual_research(
    session: Any,
    job: JobExecution,
    payload: ProcessDispatchPayload,
    base: _ProcessBase,
) -> None:
    if payload.completed_research_run_id is not None or base.route.research_mode != "manual":
        return
    from app.research.models import ResearchRun

    profile_id = _research_profile_id(base.route)
    manual_run = await session.scalar(
        select(ResearchRun)
        .where(
            ResearchRun.story_id == base.story_revision.story_id,
            ResearchRun.provider_profile_id == profile_id,
            ResearchRun.requested_mode == "manual",
            ResearchRun.status == "succeeded",
            ResearchRun.result_story_revision_id.is_not(None),
            ResearchRun.created_at >= base.dispatch.created_at,
        )
        .order_by(ResearchRun.finished_at.desc(), ResearchRun.id.desc())
        .limit(1)
    )
    if manual_run is None:
        base.dispatch.status = "needs_review"
        base.dispatch.error_code = "telegram_manual_research_required"
        base.dispatch.error_message = "Manual research is required before generation"
        session.add(
            WorkflowEvent(
                workflow_job_id=job.id,
                event_type="telegram.research.review_required",
                actor="automation",
                event_data=redact_event_data(
                    {"dispatch_id": str(base.dispatch.id), "story_id": str(base.story_revision.story_id)}
                ),
            )
        )
        raise NeedsReviewJobError(
            code="telegram_manual_research_required",
            message="Manual research is required before generation",
        )
    selected = await session.get(StoryRevision, manual_run.result_story_revision_id)
    if selected is None or selected.story_id != base.story_revision.story_id:
        raise NeedsReviewJobError(
            code="telegram_manual_research_result_invalid",
            message="Manual research result revision is invalid",
        )
    base.dispatch.story_revision_id = selected.id
    base.dispatch.status = "captured"
    base.dispatch.error_code = None
    base.dispatch.error_message = None
    base.story_revision = selected


async def _request_auto_research(
    session: Any,
    payload: ProcessDispatchPayload,
    base: _ProcessBase,
    prompt: Any,
) -> dict[str, Any] | None:
    if payload.completed_research_run_id is not None or base.route.research_mode != "auto_if_incomplete":
        return None
    from app.research.service import ResearchRequestError, ResearchService

    profile_id = _research_profile_id(base.route)
    continuation = {
        "job_type": "telegram.route.process",
        "payload": {
            "dispatch_id": str(base.dispatch.id),
            "force_review": payload.force_review,
            "prompt_template_version_id": str(prompt.id),
            "prompt_checksum": prompt.checksum_sha256,
        },
        "idempotency_prefix": f"telegram-route-process-after-research:{base.dispatch.id}",
        "subscriber_id": f"telegram-dispatch:{base.dispatch.id}",
        "expected_route_id": str(base.route.id),
        "expected_story_id": str(base.story_revision.story_id),
        "expected_story_revision_id": str(base.story_revision.id),
        "expected_provider_profile_id": str(profile_id),
        "expected_research_mode": "auto_if_incomplete",
    }
    try:
        research = await ResearchService(session).request(
            story_id=base.story_revision.story_id,
            mode="auto_if_incomplete",
            depth="standard",
            provider_profile_id=profile_id,
            query_hint=None,
            continuation=continuation,
        )
    except ResearchRequestError as exc:
        raise PermanentJobError(code="telegram_research_request_invalid", message=str(exc)) from None
    if research.disposition != "enqueued":
        return None
    base.dispatch.status = "researching"
    base.dispatch.error_code = None
    base.dispatch.error_message = None
    return {
        "dispatch_id": str(base.dispatch.id),
        "research_run_id": str(research.run_id),
        "research_job_id": str(research.job_id),
    }


async def _load_generation_config(session: Any, base: _ProcessBase, prompt: Any) -> _GenerationConfig:
    snapshot = await _exact_dispatch_evidence(session, base.story_revision.id)
    content_item, _ = await dispatch_media(session, base.source_item, lock_for_revision=False)
    brand = await session.get(BrandProfile, base.route.brand_profile_id)
    profile = await session.get(AIProviderProfile, base.route.ai_provider_profile_id)
    destination = await session.get(Destination, base.route.destination_id)
    if prompt is None or brand is None or profile is None or destination is None:
        raise PermanentJobError(
            code="telegram_route_configuration_missing",
            message="Telegram route configuration is incomplete",
        )
    return _GenerationConfig(prompt, snapshot, content_item, brand, profile)


async def _generation_run_state(
    session: Any,
    base: _ProcessBase,
    workflow_attempt_count: int,
) -> tuple[Any, list[Any], dict[str, Any] | None, dict[str, Any] | None]:
    run = (
        await session.get(GenerationRun, base.dispatch.generation_run_id)
        if base.dispatch.generation_run_id is not None
        else None
    )
    if run is not None and run.status == "completed" and run.output_payload:
        if generation_input_hash(dict(run.request_payload or {})) != run.input_hash:
            raise NeedsReviewJobError(
                code="telegram_generation_input_drift",
                message="Durable generation input no longer matches its hash",
            )
        return run, [], dict(run.output_payload), None
    if run is not None and run.status == "running":
        active_claim = int(((run.request_payload or {}).get("execution") or {}).get("active_workflow_attempt", 0))
        if active_claim == workflow_attempt_count:
            return (
                run,
                [],
                None,
                {
                    "dispatch_id": str(base.dispatch.id),
                    "generation_run_id": str(run.id),
                    "already_in_progress": True,
                },
            )
    attempts = await _load_generation_attempts(session, run)
    if run is not None and run.status == "running":
        _supersede_running_attempts(attempts)
    return run, attempts, None, None


async def _load_generation_attempts(session: Any, run: Any) -> list[Any]:
    if run is None:
        return []
    return list(
        await session.scalars(
            select(GenerationAttempt)
            .where(GenerationAttempt.generation_run_id == run.id)
            .order_by(GenerationAttempt.attempt_number)
            .with_for_update()
        )
    )


def _supersede_running_attempts(attempts: list[Any]) -> None:
    for attempt in attempts:
        if attempt.status == "running":
            attempt.status = "failed"
            attempt.error_class = "retryable"
            attempt.error_code = "stale_generation_attempt"
            attempt.error_message = "Generation attempt lease was superseded"
            attempt.finished_at = datetime.now(UTC)


async def _resolve_generation_provider(
    dependencies: TelegramProcessDependencies,
    profile: Any,
    model_override: Any,
    route: Any,
    job: JobExecution,
) -> Any:
    try:
        return await dependencies.profile_resolver.resolve(profile, model_override)
    except Exception as exc:
        mapped = _generation_error(exc, route, job)
        if mapped is exc:
            raise
        raise mapped from None


def _render_generation_input(base: _ProcessBase, config: _GenerationConfig) -> tuple[dict[str, Any], str]:
    rewrite_input = TelegramRewriteInput.model_validate(
        {
            "source_text": config.snapshot.content_text,
            "source_url": config.snapshot.source_url,
            "source_channel": base.source_item.external_id_norm or str(base.route.source_id),
            "language": config.brand.output_language,
            "direction": config.content_item.direction or "ltr",
            "attribution_policy": base.route.attribution_policy,
            "custom_footer": base.route.custom_footer,
        }
    )
    values = rewrite_input.model_dump(mode="json")
    try:
        return values, config.prompt.user_template.format(**values)
    except KeyError, ValueError:
        raise PermanentJobError(
            code="telegram_prompt_invalid",
            message="Telegram prompt template cannot be rendered",
        ) from None


def _generation_request_payload(
    base: _ProcessBase,
    config: _GenerationConfig,
    resolved: Any,
    values: dict[str, Any],
    workflow_job_id: UUID,
    workflow_attempt_count: int,
    requested_model: Any,
) -> dict[str, Any]:
    return _redacted_dict(
        {
            "semantic": {
                "dispatch_id": str(base.dispatch.id),
                "route_id": str(base.route.id),
                "story_revision_id": str(base.story_revision.id),
                "evidence_snapshot_id": str(config.snapshot.id),
                "prompt_template_version_id": str(config.prompt.id),
                "prompt_checksum": config.prompt.checksum_sha256,
                "provider_profile_id": str(config.profile.id),
                "requested_model": requested_model,
                "selected_model": resolved.model,
            },
            "input": values,
            "execution": {
                "active_workflow_job_id": str(workflow_job_id),
                "active_workflow_attempt": workflow_attempt_count,
            },
        }
    )


async def _upsert_generation_run(
    session: Any,
    base: _ProcessBase,
    config: _GenerationConfig,
    run: Any,
    request_payload: dict[str, Any],
    requested_model: Any,
) -> Any:
    computed_hash = generation_input_hash(request_payload)
    if computed_hash is None:  # pragma: no cover - constructed above
        raise RuntimeError("Generation input hash could not be computed")
    if run is None:
        run = GenerationRun(
            story_revision_id=base.story_revision.id,
            provider_profile_id=config.profile.id,
            prompt_template_version_id=config.prompt.id,
            requested_model=redact_string(requested_model) if requested_model is not None else None,
            status="running",
            input_hash=computed_hash,
            request_payload=request_payload,
            output_payload={},
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        base.dispatch.generation_run_id = run.id
        return run
    existing_hash = generation_input_hash(dict(run.request_payload or {}))
    if existing_hash != run.input_hash or computed_hash != run.input_hash:
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
    return run


async def _create_generation_attempt(
    session: Any,
    base: _ProcessBase,
    config: _GenerationConfig,
    run: Any,
    attempts: list[Any],
    resolved: Any,
    requested_model: Any,
    rendered_user: str,
    request_payload: dict[str, Any],
) -> _PreparedProcess:
    base.dispatch.status = "generating"
    base.dispatch.error_code = None
    base.dispatch.error_message = None
    attempt = GenerationAttempt(
        generation_run_id=run.id,
        attempt_number=max((item.attempt_number for item in attempts), default=0) + 1,
        provider=resolved.provider_type,
        requested_model=redact_string(requested_model) if requested_model is not None else None,
        prompt_snapshot=_redacted_dict(
            {"system": config.prompt.system_template, "user": rendered_user, "schema": config.prompt.output_schema}
        ),
        response_payload={},
        usage={},
        validation_errors=[],
        status="running",
        started_at=datetime.now(UTC),
    )
    session.add(attempt)
    await session.flush()
    run.request_payload = _redacted_dict(
        {
            **request_payload,
            "execution": {
                **request_payload["execution"],
                "active_generation_attempt_id": str(attempt.id),
            },
        }
    )
    provider_request = GenerationProviderRequest(
        run_id=run.id,
        purpose="telegram_rewrite",
        requested_model=resolved.model,
        messages=(
            ProviderMessage(role="system", content=config.prompt.system_template),
            ProviderMessage(role="user", content=rendered_user),
        ),
        response_schema=dict(config.prompt.output_schema or {}),
        metadata={
            "dispatch_id": str(base.dispatch.id),
            "route_id": str(base.route.id),
            "evidence_snapshot_id": str(config.snapshot.id),
            "provider_profile_id": str(config.profile.id),
        },
    )
    return _PreparedProcess(base.route, resolved.provider, provider_request, attempt.id)


async def _prepare_process_dispatch(
    job: JobExecution,
    context: JobContext,
    payload: ProcessDispatchPayload,
    dependencies: TelegramProcessDependencies,
) -> _PreparedProcess | dict[str, Any]:
    session = context.session
    async with session.begin():
        base = await _load_process_base(session, payload)
        if isinstance(base, dict):
            return base
        await _validate_research_continuation(session, payload, base.story_revision)
        await _apply_manual_research(session, job, payload, base)
        prompt = await resolve_process_prompt(
            session,
            route=base.route,
            payload=payload,
            workflow_job_id=job.id,
        )
        research = await _request_auto_research(session, payload, base, prompt)
        if research is not None:
            return research
        config = await _load_generation_config(session, base, prompt)
        run, attempts, durable_output, short_circuit = await _generation_run_state(
            session,
            base,
            job.attempt_count,
        )
        if short_circuit is not None:
            return short_circuit
        if durable_output is not None:
            return _PreparedProcess(base.route, durable_output=durable_output)
        model_override = (base.route.content_filters or {}).get("model")
        resolved = await _resolve_generation_provider(
            dependencies,
            config.profile,
            model_override,
            base.route,
            job,
        )
        values, rendered_user = _render_generation_input(base, config)
        requested_model = model_override or config.profile.default_model
        request_payload = _generation_request_payload(
            base,
            config,
            resolved,
            values,
            job.id,
            job.attempt_count,
            requested_model,
        )
        run = await _upsert_generation_run(
            session,
            base,
            config,
            run,
            request_payload,
            requested_model,
        )
        return await _create_generation_attempt(
            session,
            base,
            config,
            run,
            attempts,
            resolved,
            requested_model,
            rendered_user,
            request_payload,
        )


async def _process_route_dispatch(
    job: JobExecution,
    context: JobContext,
    *,
    dependencies: TelegramProcessDependencies,
) -> dict[str, Any]:
    payload = _parse_payload(ProcessDispatchPayload, job_payload_copy(job))
    prepared = await _prepare_process_dispatch(job, context, payload, dependencies)
    if isinstance(prepared, dict):
        return prepared
    if prepared.durable_output is None:
        if prepared.provider is None or prepared.provider_request is None or prepared.active_attempt_id is None:
            raise RuntimeError("Telegram generation attempt was not prepared")
        short_circuit = await _invoke_and_persist_generation(
            _GenerationPhase(
                session=context.session,
                job=job,
                payload=payload,
                workflow_job_id=job.id,
                route=prepared.route,
                provider=prepared.provider,
                provider_request=prepared.provider_request,
                active_attempt_id=prepared.active_attempt_id,
                dependencies=dependencies,
            )
        )
        if short_circuit is not None:
            return short_circuit
    return await _persist_revision_and_publish(
        _RevisionPhase(
            session=context.session,
            payload=payload,
            workflow_job_id=job.id,
            workflow_attempt_count=job.attempt_count,
        )
    )
