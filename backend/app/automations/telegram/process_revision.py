from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.decisions import evaluate_review_policy
from app.automations.telegram.handler_contracts import (
    ProcessDispatchPayload,
    build_evidence_map,
    sha256_canonical,
)
from app.automations.telegram.policy import evaluate_auto_publish
from app.automations.telegram.process_support import (
    _content_pack_and_variant,
    _exact_dispatch_evidence,
    _route_parent_revision,
    dispatch_media,
    enqueue_telegram_publish_intent,
    media_decision,
    require_automation_variant_write_allowed,
)
from app.automations.telegram.route_policy import retry_at
from app.db.models import SourceItem
from app.generation.models import GenerationAttempt, GenerationRun, PlatformVariantRevision
from app.generation.telegram_schema import TelegramRewriteOutput, TelegramVariantContent
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent
from app.publishing.models import Destination
from app.stories.models import StoryRevision


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
