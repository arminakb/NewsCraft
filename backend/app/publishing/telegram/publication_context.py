from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.automations.models import AutomationDispatch, AutomationRoute
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.generation.telegram_schema import TelegramVariantContent
from app.jobs.errors import NeedsReviewJobError, PermanentJobError
from app.jobs.models import AutomationControl
from app.publishing.models import Destination, Publication, PublishJob
from app.publishing.telegram.scheduling import _canonical_hash, _revision_dispatch

_ROUTE_UNSET = object()


async def _load_publish_intent(session: Any, publish_job_id: UUID) -> tuple[Any, Any] | dict[str, Any]:
    revision_id = await session.scalar(
        select(PublishJob.platform_variant_revision_id).where(PublishJob.id == publish_job_id)
    )
    if revision_id is None:
        raise PermanentJobError(code="telegram_publish_job_missing", message="Telegram publish job was not found")
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.id == revision_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    publish_job = await session.scalar(
        select(PublishJob)
        .where(PublishJob.id == publish_job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if revision is None or publish_job is None or publish_job.platform_variant_revision_id != revision.id:
        raise PermanentJobError(
            code="telegram_publish_context_missing",
            message="Telegram publish context is incomplete",
        )
    existing = await session.scalar(
        select(Publication)
        .where(Publication.publish_job_id == publish_job.id)
        .execution_options(populate_existing=True)
    )
    if existing is None:
        return revision, publish_job
    if (
        existing.reconciliation_status != "confirmed"
        or existing.destination_id != publish_job.destination_id
        or existing.platform_variant_revision_id != publish_job.platform_variant_revision_id
        or existing.payload_hash != publish_job.payload_hash
    ):
        raise NeedsReviewJobError(
            code="telegram_publication_drift",
            message="Existing publication does not match the publish intent",
        )
    return {
        "publish_job_id": str(publish_job.id),
        "publication_id": str(existing.id),
        "remote_message_ids": list(existing.remote_message_ids),
        "permalink": existing.permalink,
        "idempotent": True,
    }


async def _load_publish_revision(session: Any, revision: Any) -> tuple[Any, TelegramVariantContent]:
    variant = await session.get(PlatformVariant, revision.platform_variant_id, populate_existing=True)
    if variant is None or variant.platform != "telegram":
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
    exact_hash = _canonical_hash({"content": revision.content, "evidence_map": revision.evidence_map})
    if exact_hash != revision.content_hash:
        raise NeedsReviewJobError(
            code="telegram_revision_hash_drift",
            message="Telegram revision hash no longer matches",
        )
    return variant, content


async def _load_publish_route(
    session: Any,
    revision: Any,
    publish_job: Any,
    expected_proxy_profile_id: UUID | None | object,
) -> tuple[Any, Any, Any]:
    ancestor = await _revision_dispatch(session, revision)
    if ancestor is None:
        raise NeedsReviewJobError(
            code="telegram_route_provenance_missing",
            message="Telegram revision has no route provenance",
        )
    dispatch = await session.scalar(
        select(AutomationDispatch)
        .where(AutomationDispatch.id == ancestor.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if dispatch is None:
        raise NeedsReviewJobError(
            code="telegram_route_provenance_missing",
            message="Telegram revision has no route provenance",
        )
    route = await session.scalar(
        select(AutomationRoute)
        .where(AutomationRoute.id == dispatch.route_id)
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
        .where(Destination.id == publish_job.destination_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    _validate_publish_route(route, control, destination, publish_job, expected_proxy_profile_id)
    return dispatch, route, destination


def _validate_publish_route(
    route: Any,
    control: Any,
    destination: Any,
    publish_job: Any,
    expected_proxy_profile_id: UUID | None | object,
) -> None:
    if destination is None:
        raise PermanentJobError(
            code="telegram_publish_context_missing",
            message="Telegram publish context is incomplete",
        )
    if expected_proxy_profile_id is not _ROUTE_UNSET and destination.proxy_profile_id != expected_proxy_profile_id:
        raise NeedsReviewJobError(
            code="telegram_publish_route_changed",
            message="Telegram destination route changed before dispatch",
        )
    if route is None or route.destination_id != destination.id:
        raise NeedsReviewJobError(
            code="telegram_publish_route_drift", message="Telegram publish route no longer matches"
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
