from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.handlers import enqueue_telegram_publish_intent
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.generation.revision_validation import RevisionValidationError, validate_approvable_revision
from app.jobs.errors import NeedsReviewJobError
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent
from app.publishing.models import Destination, PublishJob


class ReviewedTelegramDraftError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 409) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class DraftPublicationResult:
    revision: PlatformVariantRevision
    publish_job: PublishJob


def require_revision_transition(
    revision: Any,
    *,
    content_hash: str,
) -> None:
    if revision.content_hash != content_hash:
        raise ReviewedTelegramDraftError("Draft content changed")
    if revision.approval_state != "approved":
        raise ReviewedTelegramDraftError("Draft cannot publish from its current state")
    try:
        validate_approvable_revision(revision)
    except RevisionValidationError as exc:
        raise ReviewedTelegramDraftError(str(exc)) from None
    if bool((revision.content or {}).get("dry_run")):
        raise ReviewedTelegramDraftError("Dry-run drafts cannot be published")


async def revision_dispatch(
    session: AsyncSession,
    revision: PlatformVariantRevision,
) -> AutomationDispatch | None:
    variant = await session.get(PlatformVariant, revision.platform_variant_id)
    if variant is None or variant.platform != "telegram":
        return None
    expected_variant_id = revision.platform_variant_id
    current: PlatformVariantRevision | None = revision
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
            if current.parent_revision_id is not None
            else None
        )
    return None


async def locked_revision(
    session: AsyncSession,
    revision_id: UUID,
) -> PlatformVariantRevision:
    provisional = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.id == revision_id)
        .execution_options(populate_existing=True)
    )
    if provisional is None:
        raise ReviewedTelegramDraftError("Telegram draft not found", status_code=404)
    variant = await session.scalar(
        select(PlatformVariant)
        .where(PlatformVariant.id == provisional.platform_variant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if variant is None or variant.platform != "telegram":
        raise ReviewedTelegramDraftError("Telegram draft not found", status_code=404)
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .where(
            PlatformVariantRevision.id == revision_id,
            PlatformVariantRevision.platform_variant_id == variant.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if revision is None:
        raise ReviewedTelegramDraftError("Telegram draft not found", status_code=404)
    latest_id = await session.scalar(
        select(PlatformVariantRevision.id)
        .where(PlatformVariantRevision.platform_variant_id == revision.platform_variant_id)
        .order_by(
            PlatformVariantRevision.revision_number.desc(),
            PlatformVariantRevision.created_at.desc(),
            PlatformVariantRevision.id.desc(),
        )
        .limit(1)
    )
    if latest_id != revision.id:
        raise ReviewedTelegramDraftError("Telegram draft revision is not current")
    return revision


def append_draft_event(
    session: AsyncSession,
    *,
    event_type: str,
    revision: PlatformVariantRevision,
    data: dict[str, Any] | None = None,
) -> None:
    session.add(
        WorkflowEvent(
            workflow_job_id=None,
            event_type=event_type,
            actor="operator",
            event_data=redact_event_data(
                {
                    "revision_id": str(revision.id),
                    "content_hash": revision.content_hash,
                    **(data or {}),
                }
            ),
        )
    )


async def publish_reviewed_draft(
    session: AsyncSession,
    *,
    revision_id: UUID,
    content_hash: str,
    capability_status: Any,
) -> DraftPublicationResult:
    revision = await locked_revision(session, revision_id)
    require_revision_transition(revision, content_hash=content_hash)
    dispatch = await revision_dispatch(session, revision)
    if dispatch is None:
        raise ReviewedTelegramDraftError("Telegram draft has no route provenance")
    route = await session.get(AutomationRoute, dispatch.route_id)
    if route is None:
        raise ReviewedTelegramDraftError("Telegram draft route is missing")
    destination = await session.scalar(
        select(Destination).where(Destination.id == route.destination_id).with_for_update()
    )
    if destination is None:
        raise ReviewedTelegramDraftError("Telegram draft destination is missing")
    await capability_status.require_available(
        "destination",
        destination.id,
        "publishing",
        job_type="telegram.publish",
    )
    try:
        publish_job = await enqueue_telegram_publish_intent(
            session,
            revision=revision,
            destination=destination,
            dispatch=dispatch if dispatch.variant_revision_id == revision.id else None,
        )
    except NeedsReviewJobError as exc:
        if exc.code != "telegram_publish_already_scheduled":
            raise
        raise ReviewedTelegramDraftError(
            "Telegram draft is already scheduled for publication",
        ) from None
    append_draft_event(
        session,
        event_type="telegram.revision.publish_requested",
        revision=revision,
        data={"publish_job_id": str(publish_job.id)},
    )
    await session.flush()
    return DraftPublicationResult(revision=revision, publish_job=publish_job)
