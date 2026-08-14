from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.decisions import (
    reconciliation_required,
)
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_secrets, redact_string
from app.db.models import ItemMedia, MediaAsset, SourceItem
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.telegram_schema import (
    TelegramEvidenceCitation,
    TelegramVariantContent,
)
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent
from app.publishing.models import (
    Destination,
    Publication,
    PublishAttempt,
    PublishJob,
    PublishOperationReceipt,
)
from app.publishing.telegram.client import (
    TelegramRetryableBeforeDispatch,
)
from app.publishing.telegram.publication_context import (
    _ROUTE_UNSET,
    _load_publish_intent,
    _load_publish_revision,
    _load_publish_route,
)
from app.publishing.telegram.publication_context import (
    _validate_publish_route as _validate_publish_route,
)
from app.publishing.telegram.publication_support import (
    _ClaimOutcome,
    _close_running_publish_attempts,
    _mark_publish_blocked,
    _PublishContext,
    _record_failure,
    _release_claim_for_retry,
    _short_circuit_result,
)
from app.publishing.telegram.reconciliation import (
    derive_telegram_permalink,
    ordered_receipt_remote_ids,
    validate_publish_evidence,
    validate_receipt_plan,
)
from app.publishing.telegram.renderer import TelegramPublishNeedsReview, build_publish_plan
from app.publishing.telegram.scheduling import _canonical_hash
from app.publishing.telegram.secret_resolution import resolve_destination_secret
from app.publishing.telegram.service_contracts import (
    PublishValidationError,
)
from app.stories.models import StoryEvidenceSnapshot, StoryRevision


async def _validate_publish_evidence_context(
    session: Any,
    revision: Any,
    variant: Any,
    dispatch: Any,
) -> None:
    pack = await session.get(ContentPack, variant.content_pack_id, populate_existing=True)
    story_revision = await session.get(StoryRevision, pack.story_revision_id, populate_existing=True) if pack else None
    try:
        citations = [TelegramEvidenceCitation.model_validate(item) for item in revision.evidence_map]
    except Exception:
        raise NeedsReviewJobError(
            code="telegram_publish_evidence_invalid",
            message="Telegram publish evidence is invalid",
        ) from None
    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot)
            .where(StoryEvidenceSnapshot.id.in_([item.evidence_snapshot_id for item in citations]))
            .execution_options(populate_existing=True)
        )
    )
    try:
        validate_publish_evidence(revision.evidence_map, snapshots)
    except PublishValidationError as exc:
        raise NeedsReviewJobError(code=exc.code, message=str(exc)) from None
    if (
        story_revision is None
        or any(snapshot.story_id != story_revision.story_id for snapshot in snapshots)
        or dispatch.story_revision_id != story_revision.id
    ):
        raise NeedsReviewJobError(
            code="telegram_publish_evidence_story_drift",
            message="Telegram evidence no longer belongs to the revision story",
        )


async def _load_publish_plan_receipts(
    session: Any,
    revision: Any,
    content: TelegramVariantContent,
    destination: Any,
    publish_job: Any,
) -> tuple[Any, list[Any]]:
    media = list(
        await session.scalars(
            select(MediaAsset)
            .where(MediaAsset.id.in_(list(content.media_asset_ids)))
            .execution_options(populate_existing=True)
        )
    )
    try:
        plan = build_publish_plan(revision, media, destination)
    except TelegramPublishNeedsReview as exc:
        raise NeedsReviewJobError(code="telegram_publish_plan_invalid", message=str(exc)) from None
    receipts = list(
        await session.scalars(
            select(PublishOperationReceipt)
            .where(PublishOperationReceipt.publish_job_id == publish_job.id)
            .order_by(PublishOperationReceipt.operation_index)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if not receipts:
        receipts = [
            PublishOperationReceipt(
                publish_job_id=publish_job.id,
                operation_index=operation.index,
                operation_key=operation.key,
                method=operation.method,
                request_hash=operation.request_hash,
                status="pending",
            )
            for operation in plan.operations
        ]
        session.add_all(receipts)
        await session.flush()
    try:
        validate_receipt_plan(receipts, plan.operations)
    except PublishValidationError as exc:
        raise NeedsReviewJobError(code=exc.code, message=str(exc)) from None
    publish_job.payload_hash = plan.payload_hash
    return plan, receipts


async def _publish_receipt_short_circuit(
    session: Any,
    publish_job: Any,
    receipts: list[Any],
    observed_at: datetime,
) -> dict[str, Any] | None:
    ambiguous = next((item for item in receipts if reconciliation_required(receipt_status=item.status)), None)
    if ambiguous is not None:
        publish_job.status = "reconciliation_required"
        return {"publish_job_id": str(publish_job.id), "reconciliation_required": True}
    dispatching = next((item for item in receipts if item.status == "dispatching"), None)
    if dispatching is not None:
        return await _dispatching_receipt_result(session, publish_job, dispatching, observed_at)
    first_incomplete = next((item for item in receipts if item.status != "succeeded"), None)
    retry_at = first_incomplete.next_attempt_at if first_incomplete is not None else None
    if retry_at is not None and retry_at > observed_at:
        return {"publish_job_id": str(publish_job.id), "retry_at": retry_at}
    if receipts and all(item.status == "succeeded" for item in receipts):
        await _close_running_publish_attempts(
            session,
            publish_job_id=publish_job.id,
            status="failed",
            error_class="retryable",
            error_code="telegram_publish_attempt_interrupted",
            error_message="Prior Telegram publish attempt was interrupted after durable receipt",
            finished_at=observed_at,
        )
    return None


async def _dispatching_receipt_result(
    session: Any,
    publish_job: Any,
    dispatching: Any,
    observed_at: datetime,
) -> dict[str, Any]:
    stale = bool(dispatching.updated_at and dispatching.updated_at < observed_at - timedelta(minutes=5))
    if reconciliation_required(receipt_status=dispatching.status, dispatch_stale=stale):
        dispatching.status = "ambiguous"
        dispatching.ambiguous_at = observed_at
        publish_job.status = "reconciliation_required"
        await _close_running_publish_attempts(
            session,
            publish_job_id=publish_job.id,
            status="needs_review",
            error_class="needs_review",
            error_code="telegram_publish_ambiguous",
            error_message="Telegram publish outcome is ambiguous after worker interruption",
            finished_at=observed_at,
        )
        return {"publish_job_id": str(publish_job.id), "reconciliation_required": True}
    return {
        "publish_job_id": str(publish_job.id),
        "in_progress": True,
        "retry_at": (dispatching.updated_at or observed_at) + timedelta(minutes=5),
    }


async def _create_publish_attempt(
    session: Any,
    publish_job: Any,
    revision: Any,
    destination: Any,
    plan: Any,
    observed_at: datetime,
) -> Any:
    attempt_number = (
        int(
            await session.scalar(
                select(func.coalesce(func.max(PublishAttempt.attempt_number), 0)).where(
                    PublishAttempt.publish_job_id == publish_job.id
                )
            )
            or 0
        )
        + 1
    )
    attempt = PublishAttempt(
        publish_job_id=publish_job.id,
        attempt_number=attempt_number,
        sanitized_payload={
            "publish_job_id": str(publish_job.id),
            "revision_id": str(revision.id),
            "destination_id": str(destination.id),
            "payload_hash": plan.payload_hash,
            "operations": [
                {
                    "index": operation.index,
                    "key": operation.key,
                    "method": operation.method,
                    "request_hash": operation.request_hash,
                    "upload_count": len(operation.file_paths),
                }
                for operation in plan.operations
            ],
        },
        payload_hash=plan.payload_hash,
        status="running",
        started_at=observed_at,
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def load_context(
    session: Any,
    publish_job_id: UUID,
    observed_at: datetime,
    expected_proxy_profile_id: UUID | None | object = _ROUTE_UNSET,
) -> _PublishContext | dict:
    intent = await _load_publish_intent(session, publish_job_id)
    if isinstance(intent, dict):
        return intent
    revision, publish_job = intent
    variant, content = await _load_publish_revision(session, revision)
    dispatch, route, destination = await _load_publish_route(
        session,
        revision,
        publish_job,
        expected_proxy_profile_id,
    )
    await _validate_publish_evidence_context(session, revision, variant, dispatch)
    plan, receipts = await _load_publish_plan_receipts(
        session,
        revision,
        content,
        destination,
        publish_job,
    )
    short_circuit = await _publish_receipt_short_circuit(
        session,
        publish_job,
        receipts,
        observed_at,
    )
    if short_circuit is not None:
        return short_circuit
    attempt = await _create_publish_attempt(
        session,
        publish_job,
        revision,
        destination,
        plan,
        observed_at,
    )
    return _PublishContext(
        publish_job_id=publish_job.id,
        destination_id=destination.id,
        destination_secret_ref=destination.secret_ref,
        proxy_profile_id=destination.proxy_profile_id,
        target_ref=destination.target_ref,
        revision_id=revision.id,
        dispatch_id=dispatch.id,
        route_id=route.id,
        plan=plan,
        attempt_id=attempt.id,
    )


async def _load_claim_context(session: Any, context: _PublishContext) -> tuple[Any, Any, Any, Any, Any, Any]:
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.id == context.revision_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    publish_job = await session.scalar(
        select(PublishJob)
        .where(PublishJob.id == context.publish_job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    dispatch = (
        await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.id == context.dispatch_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if context.dispatch_id is not None
        else None
    )
    route = await session.scalar(
        select(AutomationRoute)
        .where(AutomationRoute.id == context.route_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    control = await session.scalar(
        select(AutomationControl)
        .where(AutomationControl.id == "global")
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    destination = await session.scalar(
        select(Destination)
        .where(Destination.id == context.destination_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if any(item is None for item in (revision, publish_job, dispatch, route, destination, control)):
        raise NeedsReviewJobError(
            code="telegram_publish_context_drift",
            message="Telegram publish context changed before dispatch",
        )
    return revision, publish_job, dispatch, route, control, destination


def _validate_claim_controls(
    context: _PublishContext,
    revision: Any,
    publish_job: Any,
    dispatch: Any,
    route: Any,
    control: Any,
    destination: Any,
) -> TelegramVariantContent:
    try:
        content = TelegramVariantContent.model_validate(revision.content)
    except Exception:
        raise NeedsReviewJobError(
            code="telegram_revision_invalid",
            message="Telegram revision content changed before dispatch",
        ) from None
    if (
        revision.approval_state != "approved"
        or content.dry_run
        or _canonical_hash({"content": revision.content, "evidence_map": revision.evidence_map})
        != revision.content_hash
        or dispatch.route_id != route.id
        or route.destination_id != destination.id
        or route.paused_at is not None
        or not route.enabled
        or control.global_pause
        or control.dry_run
        or destination.platform != "telegram"
        or not destination.enabled
        or destination.health_status != "healthy"
        or destination.secret_ref != context.destination_secret_ref
        or destination.proxy_profile_id != context.proxy_profile_id
        or destination.target_ref != context.target_ref
        or publish_job.platform_variant_revision_id != revision.id
        or publish_job.destination_id != destination.id
        or publish_job.payload_hash != context.plan.payload_hash
    ):
        raise NeedsReviewJobError(
            code="telegram_publish_context_drift",
            message="Telegram publish controls changed before dispatch",
        )
    if content.source_item_id != dispatch.source_item_id:
        raise NeedsReviewJobError(
            code="telegram_publish_source_drift",
            message="Telegram revision no longer matches its source dispatch",
        )
    return content


async def _validate_claim_evidence(session: Any, revision: Any, dispatch: Any) -> None:
    variant = await session.get(PlatformVariant, revision.platform_variant_id, populate_existing=True)
    pack = await session.get(ContentPack, variant.content_pack_id, populate_existing=True) if variant else None
    story_revision = await session.get(StoryRevision, pack.story_revision_id, populate_existing=True) if pack else None
    try:
        citations = [TelegramEvidenceCitation.model_validate(item) for item in revision.evidence_map]
    except Exception:
        raise NeedsReviewJobError(
            code="telegram_publish_evidence_invalid",
            message="Telegram evidence changed before dispatch",
        ) from None
    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot)
            .where(StoryEvidenceSnapshot.id.in_([item.evidence_snapshot_id for item in citations]))
            .execution_options(populate_existing=True)
        )
    )
    try:
        validate_publish_evidence(revision.evidence_map, snapshots)
    except PublishValidationError as exc:
        raise NeedsReviewJobError(code=exc.code, message=str(exc)) from None
    if (
        story_revision is None
        or dispatch.story_revision_id != story_revision.id
        or any(snapshot.story_id != story_revision.story_id for snapshot in snapshots)
    ):
        raise NeedsReviewJobError(
            code="telegram_publish_evidence_story_drift",
            message="Telegram evidence lineage changed before dispatch",
        )


async def _validate_claim_media_lineage(session: Any, content: TelegramVariantContent, dispatch: Any) -> None:
    if content.media_policy != "preserve" or not content.media_asset_ids:
        return
    source_item = await session.get(SourceItem, dispatch.source_item_id, populate_existing=True)
    linked_ids = (
        set(
            await session.scalars(
                select(ItemMedia.media_asset_id).where(ItemMedia.content_item_id == source_item.content_item_id)
            )
        )
        if source_item is not None
        else set()
    )
    if not set(content.media_asset_ids).issubset(linked_ids):
        raise NeedsReviewJobError(
            code="telegram_publish_media_lineage_drift",
            message="Telegram revision media no longer belongs to its source",
        )


async def _validate_claim_plan(
    session: Any,
    context: _PublishContext,
    revision: Any,
    content: TelegramVariantContent,
    destination: Any,
) -> None:
    media = list(
        await session.scalars(
            select(MediaAsset)
            .where(MediaAsset.id.in_(list(content.media_asset_ids)))
            .execution_options(populate_existing=True)
        )
    )
    try:
        current_plan = build_publish_plan(revision, media, destination)
    except TelegramPublishNeedsReview as exc:
        raise NeedsReviewJobError(code="telegram_publish_plan_drift", message=str(exc)) from None
    prepared_operations = [
        (operation.index, operation.key, operation.method, operation.request_hash)
        for operation in context.plan.operations
    ]
    current_operations = [
        (operation.index, operation.key, operation.method, operation.request_hash)
        for operation in current_plan.operations
    ]
    if current_plan.payload_hash != context.plan.payload_hash or current_operations != prepared_operations:
        raise NeedsReviewJobError(
            code="telegram_publish_plan_drift",
            message=(
                "Telegram publish plan changed before dispatch"
                if current_plan.payload_hash != context.plan.payload_hash
                else "Telegram publish operations changed before dispatch"
            ),
        )


async def revalidate_claim(session: Any, context: _PublishContext) -> PublishJob:
    revision, publish_job, dispatch, route, control, destination = await _load_claim_context(session, context)
    content = _validate_claim_controls(
        context,
        revision,
        publish_job,
        dispatch,
        route,
        control,
        destination,
    )
    await _validate_claim_evidence(session, revision, dispatch)
    await _validate_claim_media_lineage(session, content, dispatch)
    await _validate_claim_plan(session, context, revision, content, destination)
    return publish_job


async def _prepare_publish(
    session: Any,
    publish_job_id: UUID,
    observed_at: datetime,
    *,
    expected_proxy_profile_id: UUID | None | object,
) -> Any:
    try:
        async with session.begin():
            return await load_context(
                session,
                publish_job_id,
                observed_at,
                expected_proxy_profile_id=expected_proxy_profile_id,
            )
    except (NeedsReviewJobError, PermanentJobError) as exc:
        await _mark_publish_blocked(session, publish_job_id, exc.code)
        raise


async def _finish_claim_attempt(
    session: Any,
    attempt_id: UUID,
    claim_time: datetime,
    *,
    status: str,
    error_class: str,
    error_code: str,
    error_message: str,
) -> None:
    attempt = await session.get(PublishAttempt, attempt_id, populate_existing=True)
    if attempt is not None and attempt.status == "running":
        attempt.status = status
        attempt.error_class = error_class
        attempt.error_code = redact_string(error_code)
        attempt.error_message = redact_string(error_message)
        attempt.finished_at = claim_time


async def _apply_claim_state(
    session: Any,
    prepared: _PublishContext,
    publish_job: Any,
    receipt: Any,
    claim_time: datetime,
    claim_error: NeedsReviewJobError | None,
) -> _ClaimOutcome:
    if claim_error is not None:
        publish_job.status = "attention"
        await _finish_claim_attempt(
            session,
            prepared.attempt_id,
            claim_time,
            status="needs_review",
            error_class="needs_review",
            error_code=claim_error.code,
            error_message=claim_error.message,
        )
        return _ClaimOutcome(claim_error=claim_error)
    if receipt.status == "succeeded":
        return _ClaimOutcome(already_succeeded=True)
    if receipt.status == "dispatching":
        await _finish_claim_attempt(
            session,
            prepared.attempt_id,
            claim_time,
            status="failed",
            error_class="retryable",
            error_code="telegram_publish_in_progress",
            error_message="Another Telegram publish claim is in progress",
        )
        return _ClaimOutcome(
            retry_at=(receipt.updated_at or claim_time) + timedelta(minutes=5),
            competing_claim=True,
        )
    if receipt.status != "pending":
        error = NeedsReviewJobError(
            code="telegram_publish_receipt_not_sendable",
            message="Telegram publish receipt requires attention",
        )
        publish_job.status = "reconciliation_required" if receipt.status == "ambiguous" else "attention"
        await _finish_claim_attempt(
            session,
            prepared.attempt_id,
            claim_time,
            status="needs_review",
            error_class="needs_review",
            error_code=error.code,
            error_message=error.message,
        )
        return _ClaimOutcome(claim_error=error)
    if receipt.next_attempt_at and receipt.next_attempt_at > claim_time:
        return _ClaimOutcome(retry_at=receipt.next_attempt_at)
    receipt.status = "dispatching"
    receipt.attempt_count += 1
    receipt.next_attempt_at = None
    receipt.updated_at = claim_time
    publish_job.status = "dispatching"
    return _ClaimOutcome(claimed_attempt_count=receipt.attempt_count)


async def _claim_operation(
    session: Any,
    prepared: _PublishContext,
    operation: Any,
    claim_time: datetime,
) -> _ClaimOutcome:
    claim_error: NeedsReviewJobError | None = None
    async with session.begin():
        try:
            publish_job = await revalidate_claim(session, prepared)
        except NeedsReviewJobError as exc:
            claim_error = exc
            publish_job = await session.scalar(
                select(PublishJob)
                .where(PublishJob.id == prepared.publish_job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        if publish_job is None:
            raise NeedsReviewJobError(
                code="telegram_publish_job_missing",
                message="Telegram publish job is missing",
            )
        receipt = await session.scalar(
            select(PublishOperationReceipt)
            .where(
                PublishOperationReceipt.publish_job_id == prepared.publish_job_id,
                PublishOperationReceipt.operation_index == operation.index,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt is None:
            raise NeedsReviewJobError(
                code="telegram_publish_receipt_missing",
                message="Telegram publish receipt is missing",
            )
        return await _apply_claim_state(session, prepared, publish_job, receipt, claim_time, claim_error)


async def _resolve_publish_token(
    session: Any,
    prepared: _PublishContext,
    operation: Any,
    claimed_attempt_count: int,
    secret_resolver: Any,
    clock: Any,
) -> str:
    try:
        return await resolve_destination_secret(secret_resolver, prepared.destination_secret_ref)
    except Exception as exc:
        mapped = await _record_failure(
            session,
            context=prepared,
            operation=operation,
            claimed_attempt_count=claimed_attempt_count,
            error=exc,
            observed_at=clock(),
        )
        raise mapped from None


def _fault_context(prepared: _PublishContext, operation: Any, claimed_attempt_count: int) -> dict[str, Any]:
    return {
        "publish_job_id": str(prepared.publish_job_id),
        "publish_attempt_id": str(prepared.attempt_id),
        "operation_index": operation.index,
        "operation_key": operation.key,
        "method": operation.method,
        "attempt_count": claimed_attempt_count,
    }


async def _execute_publish_operation(
    session: Any,
    prepared: _PublishContext,
    operation: Any,
    claimed_attempt_count: int,
    client: Any,
    token: str,
    injector: FaultInjector,
    clock: Any,
) -> Any:
    fault_context = _fault_context(prepared, operation, claimed_attempt_count)
    try:
        await injector.hit("telegram.before_send", fault_context)
    except BaseException:
        await _record_failure(
            session,
            context=prepared,
            operation=operation,
            claimed_attempt_count=claimed_attempt_count,
            error=TelegramRetryableBeforeDispatch("Fault injected before Telegram dispatch"),
            observed_at=clock(),
        )
        raise
    try:
        result = await client.execute(operation, token)
    except Exception as exc:
        mapped = await _record_failure(
            session,
            context=prepared,
            operation=operation,
            claimed_attempt_count=claimed_attempt_count,
            error=exc,
            observed_at=clock(),
        )
        raise mapped from None
    try:
        await injector.hit(
            "telegram.after_send_before_receipt",
            {**fault_context, "remote_message_count": len(result.remote_message_ids)},
        )
    except BaseException as exc:
        await _record_failure(
            session,
            context=prepared,
            operation=operation,
            claimed_attempt_count=claimed_attempt_count,
            error=exc,
            observed_at=clock(),
        )
        raise
    return result


async def _persist_operation_receipt(
    session: Any,
    prepared: _PublishContext,
    operation: Any,
    claimed_attempt_count: int,
    result: Any,
    token: str,
    clock: Any,
) -> None:
    async with session.begin():
        receipt = await session.scalar(
            select(PublishOperationReceipt)
            .where(
                PublishOperationReceipt.publish_job_id == prepared.publish_job_id,
                PublishOperationReceipt.operation_index == operation.index,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if receipt is None or receipt.status != "dispatching" or receipt.attempt_count != claimed_attempt_count:
            raise NeedsReviewJobError(
                code="telegram_publish_claim_superseded",
                message="Telegram publish claim was superseded",
            )
        receipt.status = "succeeded"
        receipt.remote_message_ids = list(result.remote_message_ids)
        metadata = redact_secrets(result.response_metadata, secrets=(token,))
        receipt.response_metadata = metadata if isinstance(metadata, dict) else {}
        receipt.completed_at = clock()


async def _publish_one_operation(
    session: Any,
    prepared: _PublishContext,
    operation: Any,
    *,
    client: Any,
    secret_resolver: Any,
    token: str | None,
    injector: FaultInjector,
    clock: Any,
) -> str | None:
    claim = await _claim_operation(session, prepared, operation, clock())
    if claim.claim_error is not None:
        raise claim.claim_error
    if claim.already_succeeded:
        return token
    if claim.retry_at is not None:
        await _release_claim_for_retry(
            session,
            prepared,
            retry_at=claim.retry_at,
            competing_claim=claim.competing_claim,
            finished_at=clock(),
        )
        raise RetryableJobError(
            code="telegram_publish_not_due",
            message="Telegram publish retry is not due",
            retry_at=claim.retry_at,
        )
    if token is None:
        token = await _resolve_publish_token(
            session,
            prepared,
            operation,
            claim.claimed_attempt_count,
            secret_resolver,
            clock,
        )
    result = await _execute_publish_operation(
        session,
        prepared,
        operation,
        claim.claimed_attempt_count,
        client,
        token,
        injector,
        clock,
    )
    await _persist_operation_receipt(
        session,
        prepared,
        operation,
        claim.claimed_attempt_count,
        result,
        token,
        clock,
    )
    return token


async def _load_completed_publish_state(session: Any, prepared: _PublishContext) -> tuple[Any, Any, list[Any]]:
    publish_job = await session.scalar(
        select(PublishJob).where(PublishJob.id == prepared.publish_job_id).with_for_update()
    )
    attempt = await session.get(PublishAttempt, prepared.attempt_id)
    receipts = list(
        await session.scalars(
            select(PublishOperationReceipt)
            .where(PublishOperationReceipt.publish_job_id == prepared.publish_job_id)
            .order_by(PublishOperationReceipt.operation_index)
            .with_for_update()
        )
    )
    if publish_job is None or attempt is None or any(receipt.status != "succeeded" for receipt in receipts):
        raise NeedsReviewJobError(
            code="telegram_publish_incomplete",
            message="Telegram publish operation set is incomplete",
        )
    return publish_job, attempt, receipts


async def _get_or_create_publication(
    session: Any,
    prepared: _PublishContext,
    publish_job: Any,
    remote_ids: list[int],
    clock: Any,
) -> Any:
    publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job.id))
    if publication is not None:
        return publication
    publication = Publication(
        publish_job_id=publish_job.id,
        destination_id=prepared.destination_id,
        platform_variant_revision_id=prepared.revision_id,
        remote_message_ids=remote_ids,
        permalink=derive_telegram_permalink(prepared.target_ref, remote_ids),
        payload_hash=prepared.plan.payload_hash,
        published_at=clock(),
        reconciliation_status="confirmed",
    )
    try:
        async with session.begin_nested():
            session.add(publication)
            await session.flush()
    except IntegrityError:
        publication = await session.scalar(select(Publication).where(Publication.publish_job_id == publish_job.id))
        if publication is None:
            raise
    return publication


def _validate_completed_publication(
    publication: Any,
    prepared: _PublishContext,
    remote_ids: list[int],
) -> None:
    if (
        publication.destination_id != prepared.destination_id
        or publication.platform_variant_revision_id != prepared.revision_id
        or publication.payload_hash != prepared.plan.payload_hash
        or list(publication.remote_message_ids) != remote_ids
        or publication.reconciliation_status != "confirmed"
    ):
        raise NeedsReviewJobError(
            code="telegram_publication_drift",
            message="Existing publication does not match the completed operation receipts",
        )


async def _finalize_publication(
    session: Any,
    prepared: _PublishContext,
    clock: Any,
) -> dict[str, Any]:
    async with session.begin():
        publish_job, attempt, receipts = await _load_completed_publish_state(session, prepared)
        remote_ids = ordered_receipt_remote_ids(receipts)
        publication = await _get_or_create_publication(session, prepared, publish_job, remote_ids, clock)
        _validate_completed_publication(publication, prepared, remote_ids)
        publish_job.status = "succeeded"
        attempt.status = "succeeded"
        attempt.remote_response = {"remote_message_ids": remote_ids, "publication_id": str(publication.id)}
        attempt.finished_at = clock()
        dispatch = await session.get(AutomationDispatch, prepared.dispatch_id) if prepared.dispatch_id else None
        if dispatch is not None:
            dispatch.status = "published"
            dispatch.publish_job_id = publish_job.id
        session.add(
            WorkflowEvent(
                workflow_job_id=publish_job.workflow_job_id,
                event_type="telegram.publish.succeeded",
                actor="automation",
                event_data=redact_event_data(
                    {
                        "publish_job_id": str(publish_job.id),
                        "publication_id": str(publication.id),
                        "revision_id": str(prepared.revision_id),
                        "remote_message_ids": remote_ids,
                        "permalink": publication.permalink,
                    }
                ),
            )
        )
        return {
            "publish_job_id": str(publish_job.id),
            "publication_id": str(publication.id),
            "remote_message_ids": remote_ids,
            "permalink": publication.permalink,
        }


async def publish_telegram(
    session: Any,
    *,
    publish_job_id: UUID,
    client: Any,
    secret_resolver: Any,
    expected_proxy_profile_id: UUID | None | object = _ROUTE_UNSET,
    now: Any | None = None,
    fault_injector: FaultInjector | None = None,
) -> dict[str, Any]:
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()
    clock = now or (lambda: datetime.now(UTC))
    prepared = await _prepare_publish(
        session,
        publish_job_id,
        clock(),
        expected_proxy_profile_id=expected_proxy_profile_id,
    )
    if isinstance(prepared, dict):
        return _short_circuit_result(prepared)
    token: str | None = None
    for operation in prepared.plan.operations:
        token = await _publish_one_operation(
            session,
            prepared,
            operation,
            client=client,
            secret_resolver=secret_resolver,
            token=token,
            injector=injector,
            clock=clock,
        )
    await injector.hit(
        "publication.after_receipt_before_commit",
        {
            "publish_job_id": str(prepared.publish_job_id),
            "publish_attempt_id": str(prepared.attempt_id),
            "operation_count": len(prepared.plan.operations),
        },
    )
    return await _finalize_publication(session, prepared, clock)
