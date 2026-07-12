from __future__ import annotations

import hashlib
import inspect
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.automations.models import AutomationDispatch, AutomationRoute
from app.core.redaction import redact_secrets
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
    TelegramAmbiguousError,
    TelegramClientError,
    TelegramPermanentError,
    TelegramRateLimited,
    TelegramRetryableBeforeDispatch,
)
from app.publishing.telegram.renderer import TelegramPublishNeedsReview, build_publish_plan
from app.stories.models import StoryEvidenceSnapshot, StoryRevision


class PublishValidationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def validate_publish_evidence(
    evidence_map: list[dict[str, Any]],
    snapshots: Iterable[Any],
) -> list[dict[str, Any]]:
    if not evidence_map:
        raise PublishValidationError("publish_evidence_missing", "Publish evidence is missing")
    indexed = {snapshot.id: snapshot for snapshot in snapshots}
    validated: list[dict[str, Any]] = []
    for raw in evidence_map:
        try:
            citation = TelegramEvidenceCitation.model_validate(raw)
        except Exception:
            raise PublishValidationError("publish_evidence_invalid", "Publish evidence is invalid") from None
        snapshot = indexed.get(citation.evidence_snapshot_id)
        if snapshot is None:
            raise PublishValidationError("publish_evidence_snapshot_missing", "Publish evidence snapshot is missing")
        text = snapshot.content_text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            expected = TelegramEvidenceCitation(
                evidence_snapshot_id=snapshot.id,
                evidence_key=snapshot.evidence_key,
                source_url=snapshot.source_url,
                locator=f"chars:0-{len(text)}",
                excerpt_sha256=snapshot.content_sha256,
            ).model_dump(mode="json")
        except Exception:
            raise PublishValidationError(
                "publish_evidence_snapshot_invalid", "Publish evidence snapshot is invalid"
            ) from None
        if digest != snapshot.content_sha256 or citation.model_dump(mode="json") != expected:
            raise PublishValidationError("publish_evidence_drift", "Publish evidence no longer matches its snapshot")
        validated.append(citation.model_dump(mode="json"))
    return validated


def validate_receipt_plan(receipts: Sequence[Any], operations: Sequence[Any]) -> None:
    expected = [
        (operation.index, operation.key, operation.method, operation.request_hash)
        for operation in operations
    ]
    actual = [
        (receipt.operation_index, receipt.operation_key, receipt.method, receipt.request_hash)
        for receipt in sorted(receipts, key=lambda item: item.operation_index)
    ]
    if actual != expected:
        raise PublishValidationError("publish_plan_drift", "Publish operation plan drifted after receipt creation")


def ordered_receipt_remote_ids(receipts: Iterable[Any]) -> list[int]:
    remote_ids: list[int] = []
    for receipt in sorted(receipts, key=lambda item: item.operation_index):
        for message_id in receipt.remote_message_ids:
            if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
                raise PublishValidationError("remote_message_id_invalid", "Remote message IDs are invalid")
            if message_id in remote_ids:
                raise PublishValidationError("remote_message_id_duplicate", "Remote message IDs must be unique")
            remote_ids.append(message_id)
    if not remote_ids:
        raise PublishValidationError("remote_message_ids_missing", "Remote message IDs are missing")
    return remote_ids


def derive_telegram_permalink(target_ref: str, remote_message_ids: Sequence[int]) -> str | None:
    public_target = target_ref.removeprefix("@").strip()
    if not public_target or not public_target.replace("_", "").isalnum() or not remote_message_ids:
        return None
    return f"https://t.me/{public_target}/{remote_message_ids[0]}"


def validate_reconciliation(
    receipts: Sequence[Any],
    *,
    outcome: Literal["published", "not_published"],
    remote_message_ids: Sequence[int],
) -> Any:
    ambiguous = [receipt for receipt in receipts if receipt.status == "ambiguous"]
    if len(ambiguous) != 1:
        raise PublishValidationError("reconciliation_not_ambiguous", "Exactly one ambiguous operation is required")
    if outcome == "published":
        if any(receipt.status not in {"succeeded", "ambiguous"} for receipt in receipts):
            raise PublishValidationError(
                "reconciliation_incomplete",
                "Pending operations cannot be reconciled as published",
            )
        if not remote_message_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in remote_message_ids
        ):
            raise PublishValidationError(
                "reconciliation_remote_ids_invalid",
                "Verified remote message IDs are required",
            )
    else:
        if any(receipt.status not in {"succeeded", "pending", "ambiguous"} for receipt in receipts):
            raise PublishValidationError(
                "reconciliation_incomplete",
                "Unsafe operation states cannot be reconciled as not published",
            )
        if remote_message_ids:
            raise PublishValidationError(
                "reconciliation_remote_ids_forbidden",
                "Not-published outcome cannot include remote IDs",
            )
    return ambiguous[0]


def _canonical_hash(value: Any) -> str:
    import json

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _revision_dispatch(session: Any, revision: PlatformVariantRevision) -> AutomationDispatch | None:
    current: PlatformVariantRevision | None = revision
    expected_variant_id = revision.platform_variant_id
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        if current.platform_variant_id != expected_variant_id:
            return None
        seen.add(current.id)
        dispatch = await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.variant_revision_id == current.id)
            .order_by(AutomationDispatch.created_at.desc())
            .limit(1)
        )
        if dispatch is not None:
            return dispatch
        current = (
            await session.get(PlatformVariantRevision, current.parent_revision_id)
            if current.parent_revision_id
            else None
        )
    return None


async def _resolve_secret(resolver: Any, secret_ref: str) -> str:
    target = getattr(resolver, "resolve", None)
    if target is None and callable(resolver):
        target = resolver
    if target is None:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        )
    try:
        value = target(secret_ref)
        if inspect.isawaitable(value):
            value = await value
    except Exception:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        ) from None
    if not isinstance(value, str) or not value:
        raise PermanentJobError(
            code="telegram_destination_secret_missing",
            message="Destination secret is unavailable",
        )
    return value


@dataclass(frozen=True, slots=True)
class _PublishContext:
    publish_job_id: UUID
    destination_id: UUID
    destination_secret_ref: str
    target_ref: str
    revision_id: UUID
    dispatch_id: UUID | None
    route_id: UUID
    plan: Any
    attempt_id: UUID


async def _load_context(session: Any, publish_job_id: UUID, observed_at: datetime) -> _PublishContext | dict:
    publish_job = await session.scalar(
        select(PublishJob).where(PublishJob.id == publish_job_id).with_for_update()
    )
    if publish_job is None:
        raise PermanentJobError(
            code="telegram_publish_job_missing",
            message="Telegram publish job was not found",
        )
    existing_publication = await session.scalar(
        select(Publication).where(Publication.publish_job_id == publish_job.id)
    )
    if existing_publication is not None:
        if (
            existing_publication.reconciliation_status != "confirmed"
            or existing_publication.destination_id != publish_job.destination_id
            or existing_publication.platform_variant_revision_id
            != publish_job.platform_variant_revision_id
            or existing_publication.payload_hash != publish_job.payload_hash
        ):
            raise NeedsReviewJobError(
                code="telegram_publication_drift",
                message="Existing publication does not match the publish intent",
            )
        return {
            "publish_job_id": str(publish_job.id),
            "publication_id": str(existing_publication.id),
            "remote_message_ids": list(existing_publication.remote_message_ids),
            "permalink": existing_publication.permalink,
            "idempotent": True,
        }

    revision = await session.scalar(
        select(PlatformVariantRevision)
        .join(PlatformVariant, PlatformVariant.id == PlatformVariantRevision.platform_variant_id)
        .where(
            PlatformVariantRevision.id == publish_job.platform_variant_revision_id,
            PlatformVariant.platform == "telegram",
        )
    )
    destination = await session.scalar(
        select(Destination)
        .where(Destination.id == publish_job.destination_id)
        .with_for_update()
    )
    if revision is None or destination is None:
        raise PermanentJobError(
            code="telegram_publish_context_missing",
            message="Telegram publish context is incomplete",
        )
    try:
        content = TelegramVariantContent.model_validate(revision.content)
    except Exception:
        raise NeedsReviewJobError(
            code="telegram_revision_invalid",
            message="Telegram revision content is invalid",
        ) from None
    if revision.approval_state != "approved" or content.dry_run:
        raise NeedsReviewJobError(
            code="telegram_revision_not_publishable",
            message="Telegram revision is not approved for publication",
        )
    exact_hash = _canonical_hash(
        {"content": revision.content, "evidence_map": revision.evidence_map}
    )
    if exact_hash != revision.content_hash:
        raise NeedsReviewJobError(
            code="telegram_revision_hash_drift",
            message="Telegram revision hash no longer matches",
        )

    dispatch = await _revision_dispatch(session, revision)
    if dispatch is None:
        raise NeedsReviewJobError(
            code="telegram_route_provenance_missing",
            message="Telegram revision has no route provenance",
        )
    route = await session.scalar(
        select(AutomationRoute)
        .where(AutomationRoute.id == dispatch.route_id)
        .with_for_update()
    )
    control = await session.scalar(
        select(AutomationControl)
        .where(AutomationControl.id == "global")
        .with_for_update()
    )
    if route is None or route.destination_id != destination.id:
        raise NeedsReviewJobError(
            code="telegram_publish_route_drift",
            message="Telegram publish route no longer matches",
        )
    if (
        control is None
        or control.global_pause
        or control.dry_run
        or not route.enabled
        or route.paused_at is not None
        or destination.platform != "telegram"
        or not destination.enabled
        or destination.health_status != "healthy"
    ):
        raise NeedsReviewJobError(
            code="telegram_publish_gate_blocked",
            message="Telegram publication is blocked by current controls",
        )

    variant = await session.get(PlatformVariant, revision.platform_variant_id)
    pack = await session.get(ContentPack, variant.content_pack_id) if variant else None
    story_revision = await session.get(StoryRevision, pack.story_revision_id) if pack else None
    citations: list[TelegramEvidenceCitation] = []
    try:
        citations = [TelegramEvidenceCitation.model_validate(item) for item in revision.evidence_map]
    except Exception:
        raise NeedsReviewJobError(
            code="telegram_publish_evidence_invalid",
            message="Telegram publish evidence is invalid",
        ) from None
    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_([item.evidence_snapshot_id for item in citations])
            )
        )
    )
    try:
        validate_publish_evidence(revision.evidence_map, snapshots)
    except PublishValidationError as exc:
        raise NeedsReviewJobError(code=exc.code, message=str(exc)) from None
    if story_revision is None or any(
        snapshot.story_id != story_revision.story_id for snapshot in snapshots
    ) or dispatch.story_revision_id != story_revision.id:
        raise NeedsReviewJobError(
            code="telegram_publish_evidence_story_drift",
            message="Telegram evidence no longer belongs to the revision story",
        )

    media = list(
        await session.scalars(
            select(MediaAsset).where(MediaAsset.id.in_(list(content.media_asset_ids)))
        )
    )
    try:
        plan = build_publish_plan(revision, media, destination)
    except TelegramPublishNeedsReview as exc:
        raise NeedsReviewJobError(
            code="telegram_publish_plan_invalid",
            message=str(exc),
        ) from None

    receipts = list(
        await session.scalars(
            select(PublishOperationReceipt)
            .where(PublishOperationReceipt.publish_job_id == publish_job.id)
            .order_by(PublishOperationReceipt.operation_index)
            .with_for_update()
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

    ambiguous = next((item for item in receipts if item.status == "ambiguous"), None)
    if ambiguous is not None:
        publish_job.status = "reconciliation_required"
        return {
            "publish_job_id": str(publish_job.id),
            "reconciliation_required": True,
        }
    dispatching = next((item for item in receipts if item.status == "dispatching"), None)
    if dispatching is not None:
        if dispatching.updated_at and dispatching.updated_at < observed_at - timedelta(minutes=5):
            dispatching.status = "ambiguous"
            dispatching.ambiguous_at = observed_at
            publish_job.status = "reconciliation_required"
            return {
                "publish_job_id": str(publish_job.id),
                "reconciliation_required": True,
            }
        return {
            "publish_job_id": str(publish_job.id),
            "in_progress": True,
            "retry_at": (dispatching.updated_at or observed_at) + timedelta(minutes=5),
        }

    first_incomplete = next((item for item in receipts if item.status != "succeeded"), None)
    retry_at = first_incomplete.next_attempt_at if first_incomplete is not None else None
    if retry_at is not None and retry_at > observed_at:
        return {
            "publish_job_id": str(publish_job.id),
            "retry_at": retry_at,
        }

    attempt_number = int(
        await session.scalar(
            select(func.coalesce(func.max(PublishAttempt.attempt_number), 0)).where(
                PublishAttempt.publish_job_id == publish_job.id
            )
        )
        or 0
    ) + 1
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
    return _PublishContext(
        publish_job_id=publish_job.id,
        destination_id=destination.id,
        destination_secret_ref=destination.secret_ref,
        target_ref=destination.target_ref,
        revision_id=revision.id,
        dispatch_id=dispatch.id,
        route_id=route.id,
        plan=plan,
        attempt_id=attempt.id,
    )


async def _revalidate_claim(session: Any, context: _PublishContext) -> None:
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.id == context.revision_id)
        .with_for_update()
    )
    dispatch = (
        await session.scalar(
            select(AutomationDispatch)
            .where(AutomationDispatch.id == context.dispatch_id)
            .with_for_update()
        )
        if context.dispatch_id is not None
        else None
    )
    destination = await session.scalar(
        select(Destination).where(Destination.id == context.destination_id).with_for_update()
    )
    route = await session.scalar(
        select(AutomationRoute).where(AutomationRoute.id == context.route_id).with_for_update()
    )
    control = await session.scalar(
        select(AutomationControl).where(AutomationControl.id == "global").with_for_update()
    )
    if revision is None or dispatch is None or route is None or destination is None or control is None:
        raise NeedsReviewJobError(
            code="telegram_publish_context_drift",
            message="Telegram publish context changed before dispatch",
        )
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
        or destination.target_ref != context.target_ref
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
    variant = await session.get(PlatformVariant, revision.platform_variant_id)
    pack = await session.get(ContentPack, variant.content_pack_id) if variant is not None else None
    story_revision = await session.get(StoryRevision, pack.story_revision_id) if pack is not None else None
    try:
        citations = [TelegramEvidenceCitation.model_validate(item) for item in revision.evidence_map]
    except Exception:
        raise NeedsReviewJobError(
            code="telegram_publish_evidence_invalid",
            message="Telegram evidence changed before dispatch",
        ) from None
    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_([item.evidence_snapshot_id for item in citations])
            )
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
    if content.media_policy == "preserve" and content.media_asset_ids:
        source_item = await session.get(SourceItem, dispatch.source_item_id)
        linked_ids = (
            set(
                await session.scalars(
                    select(ItemMedia.media_asset_id).where(
                        ItemMedia.content_item_id == source_item.content_item_id
                    )
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
    media = list(
        await session.scalars(
            select(MediaAsset).where(MediaAsset.id.in_(list(content.media_asset_ids)))
        )
    )
    try:
        current_plan = build_publish_plan(revision, media, destination)
    except TelegramPublishNeedsReview as exc:
        raise NeedsReviewJobError(
            code="telegram_publish_plan_drift",
            message=str(exc),
        ) from None
    if current_plan.payload_hash != context.plan.payload_hash:
        raise NeedsReviewJobError(
            code="telegram_publish_plan_drift",
            message="Telegram publish plan changed before dispatch",
        )
    prepared_operations = [
        (operation.index, operation.key, operation.method, operation.request_hash)
        for operation in context.plan.operations
    ]
    current_operations = [
        (operation.index, operation.key, operation.method, operation.request_hash)
        for operation in current_plan.operations
    ]
    if current_operations != prepared_operations:
        raise NeedsReviewJobError(
            code="telegram_publish_plan_drift",
            message="Telegram publish operations changed before dispatch",
        )


async def _record_failure(
    session: Any,
    *,
    context: _PublishContext,
    operation: Any,
    claimed_attempt_count: int,
    error: Exception,
    observed_at: datetime,
) -> Exception:
    async with session.begin():
        publish_job = await session.scalar(
            select(PublishJob)
            .where(PublishJob.id == context.publish_job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        receipt = await session.scalar(
            select(PublishOperationReceipt)
            .where(
                PublishOperationReceipt.publish_job_id == context.publish_job_id,
                PublishOperationReceipt.operation_index == operation.index,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        attempt = await session.get(PublishAttempt, context.attempt_id)
        if (
            receipt is None
            or publish_job is None
            or attempt is None
            or receipt.status != "dispatching"
            or receipt.attempt_count != claimed_attempt_count
        ):
            return NeedsReviewJobError(
                code="telegram_publish_claim_superseded",
                message="Telegram publish claim was superseded",
            )
        attempt.finished_at = observed_at
        metadata = getattr(error, "metadata", {}) if isinstance(error, TelegramClientError) else {}
        safe_metadata = redact_event_data(metadata)
        if isinstance(safe_metadata, dict):
            receipt.response_metadata = safe_metadata
            attempt.remote_response = safe_metadata
            status = safe_metadata.get("http_status")
            if isinstance(status, int) and not isinstance(status, bool):
                attempt.http_status = status
        if isinstance(error, TelegramRateLimited):
            retry_at = observed_at + timedelta(seconds=error.retry_after)
            receipt.status = "pending"
            receipt.next_attempt_at = retry_at
            publish_job.status = "queued"
            publish_job.scheduled_for = retry_at
            attempt.status = "failed"
            attempt.error_class = "retryable"
            attempt.error_code = "telegram_rate_limited"
            attempt.error_message = "Telegram rate limit exceeded"
            return RetryableJobError(
                code="telegram_rate_limited",
                message="Telegram rate limit exceeded",
                retry_at=retry_at,
            )
        if isinstance(error, TelegramRetryableBeforeDispatch):
            retry_at = observed_at + timedelta(seconds=30)
            receipt.status = "pending"
            receipt.next_attempt_at = retry_at
            publish_job.status = "queued"
            publish_job.scheduled_for = retry_at
            attempt.status = "failed"
            attempt.error_class = "retryable"
            attempt.error_code = "telegram_connect_failed"
            attempt.error_message = "Telegram connection failed before dispatch"
            return RetryableJobError(
                code="telegram_connect_failed",
                message="Telegram connection failed before dispatch",
                retry_at=retry_at,
            )
        if isinstance(error, TelegramAmbiguousError) or not isinstance(
            error, (TelegramPermanentError, PermanentJobError)
        ):
            receipt.status = "ambiguous"
            receipt.ambiguous_at = observed_at
            publish_job.status = "reconciliation_required"
            attempt.status = "needs_review"
            attempt.error_class = "needs_review"
            attempt.error_code = "telegram_publish_ambiguous"
            attempt.error_message = "Telegram publish outcome is ambiguous"
            return NeedsReviewJobError(
                code="telegram_publish_ambiguous",
                message="Telegram publish outcome is ambiguous",
            )
        receipt.status = "failed"
        publish_job.status = "attention"
        attempt.status = "failed"
        attempt.error_class = "permanent"
        attempt.error_code = "telegram_publish_permanent"
        attempt.error_message = "Telegram publish operation failed permanently"
        return PermanentJobError(
            code="telegram_publish_permanent",
            message="Telegram publish operation failed permanently",
        )


async def publish_telegram(
    session: Any,
    *,
    publish_job_id: UUID,
    client: Any,
    secret_resolver: Any,
    now: Any | None = None,
) -> dict[str, Any]:
    clock = now or (lambda: datetime.now(UTC))
    observed_at = clock()
    try:
        async with session.begin():
            prepared = await _load_context(session, publish_job_id, observed_at)
    except (NeedsReviewJobError, PermanentJobError) as exc:
        async with session.begin():
            publish_job = await session.scalar(
                select(PublishJob).where(PublishJob.id == publish_job_id).with_for_update()
            )
            if publish_job is not None:
                publish_job.status = "attention"
                session.add(
                    WorkflowEvent(
                        workflow_job_id=publish_job.workflow_job_id,
                        event_type="telegram.publish.blocked",
                        actor="automation",
                        event_data=redact_event_data(
                            {
                                "publish_job_id": str(publish_job.id),
                                "error_code": exc.code,
                            }
                        ),
                    )
                )
        raise
    if isinstance(prepared, dict):
        if prepared.get("reconciliation_required"):
            raise NeedsReviewJobError(
                code="telegram_publish_reconciliation_required",
                message="Telegram publish requires reconciliation",
            )
        retry_at = prepared.get("retry_at")
        if isinstance(retry_at, datetime):
            raise RetryableJobError(
                code="telegram_publish_not_due",
                message="Telegram publish retry is not due",
                retry_at=retry_at,
            )
        return prepared

    token: str | None = None
    for operation in prepared.plan.operations:
        claimed_attempt_count = 0
        retry_at: datetime | None = None
        claim_time = clock()
        claim_error: NeedsReviewJobError | None = None
        competing_claim = False
        async with session.begin():
            publish_job = await session.scalar(
                select(PublishJob).where(PublishJob.id == prepared.publish_job_id).with_for_update()
            )
            if publish_job is None:
                raise NeedsReviewJobError(
                    code="telegram_publish_job_missing",
                    message="Telegram publish job is missing",
                )
            try:
                await _revalidate_claim(session, prepared)
            except NeedsReviewJobError as exc:
                claim_error = exc
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
            if claim_error is not None:
                attempt = await session.get(PublishAttempt, prepared.attempt_id)
                publish_job.status = "attention"
                if attempt is not None and attempt.status == "running":
                    attempt.status = "needs_review"
                    attempt.error_class = "needs_review"
                    attempt.error_code = claim_error.code
                    attempt.error_message = claim_error.message
                    attempt.finished_at = claim_time
            elif receipt.status == "succeeded":
                continue
            elif receipt.status == "dispatching":
                competing_claim = True
                retry_at = (receipt.updated_at or claim_time) + timedelta(minutes=5)
                attempt = await session.get(PublishAttempt, prepared.attempt_id)
                if attempt is not None and attempt.status == "running":
                    attempt.status = "failed"
                    attempt.error_class = "retryable"
                    attempt.error_code = "telegram_publish_in_progress"
                    attempt.error_message = "Another Telegram publish claim is in progress"
                    attempt.finished_at = claim_time
            elif receipt.status != "pending":
                claim_error = NeedsReviewJobError(
                    code="telegram_publish_receipt_not_sendable",
                    message="Telegram publish receipt requires attention",
                )
                attempt = await session.get(PublishAttempt, prepared.attempt_id)
                if receipt.status == "ambiguous":
                    publish_job.status = "reconciliation_required"
                else:
                    publish_job.status = "attention"
                if attempt is not None and attempt.status == "running":
                    attempt.status = "needs_review"
                    attempt.error_class = "needs_review"
                    attempt.error_code = claim_error.code
                    attempt.error_message = claim_error.message
                    attempt.finished_at = claim_time
            elif receipt.next_attempt_at and receipt.next_attempt_at > claim_time:
                retry_at = receipt.next_attempt_at
            else:
                receipt.status = "dispatching"
                receipt.attempt_count += 1
                receipt.next_attempt_at = None
                receipt.updated_at = claim_time
                publish_job.status = "dispatching"
                claimed_attempt_count = receipt.attempt_count
        if claim_error is not None:
            raise claim_error
        if retry_at is not None:
            async with session.begin():
                attempt = await session.get(PublishAttempt, prepared.attempt_id)
                publish_job = await session.get(PublishJob, prepared.publish_job_id)
                if attempt is not None and attempt.status == "running":
                    attempt.status = "failed"
                    attempt.error_class = "retryable"
                    attempt.error_code = "telegram_publish_not_due"
                    attempt.error_message = "Telegram publish retry is not due"
                    attempt.finished_at = clock()
                if publish_job is not None and not competing_claim:
                    publish_job.status = "queued"
                    publish_job.scheduled_for = retry_at
            raise RetryableJobError(
                code="telegram_publish_not_due",
                message="Telegram publish retry is not due",
                retry_at=retry_at,
            )
        if token is None:
            try:
                token = await _resolve_secret(secret_resolver, prepared.destination_secret_ref)
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
            if (
                receipt is None
                or receipt.status != "dispatching"
                or receipt.attempt_count != claimed_attempt_count
            ):
                raise NeedsReviewJobError(
                    code="telegram_publish_claim_superseded",
                    message="Telegram publish claim was superseded",
                )
            receipt.status = "succeeded"
            receipt.remote_message_ids = list(result.remote_message_ids)
            metadata = redact_secrets(result.response_metadata, secrets=(token,))
            receipt.response_metadata = metadata if isinstance(metadata, dict) else {}
            receipt.completed_at = clock()

    async with session.begin():
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
        if publish_job is None or attempt is None or any(
            receipt.status != "succeeded" for receipt in receipts
        ):
            raise NeedsReviewJobError(
                code="telegram_publish_incomplete",
                message="Telegram publish operation set is incomplete",
            )
        remote_ids = ordered_receipt_remote_ids(receipts)
        publication = await session.scalar(
            select(Publication).where(Publication.publish_job_id == publish_job.id)
        )
        if publication is None:
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
                publication = await session.scalar(
                    select(Publication).where(Publication.publish_job_id == publish_job.id)
                )
                if publication is None:
                    raise
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
        publish_job.status = "succeeded"
        attempt.status = "succeeded"
        attempt.remote_response = {
            "remote_message_ids": remote_ids,
            "publication_id": str(publication.id),
        }
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
