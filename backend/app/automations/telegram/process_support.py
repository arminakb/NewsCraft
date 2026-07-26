from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.automations.models import AutomationDispatch, AutomationRoute
from app.automations.telegram.decisions import (
    evaluate_media_policy,
)
from app.automations.telegram.handler_contracts import (
    ProcessDispatchPayload,
    validate_evidence_snapshot,
)
from app.automations.telegram.route_policy import retry_at
from app.db.models import ContentItem, ItemMedia, MediaAsset, SourceItem
from app.generation.models import (
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.providers.openrouter import (
    OpenRouterNeedsReviewError,
    OpenRouterPermanentError,
    OpenRouterRetryableError,
)
from app.generation.providers.profiles import ProviderProfileConfigurationError
from app.generation.revision_fence import RegenerationFenceConflict, require_revision_write_allowed
from app.generation.revision_validation import RevisionValidationError, validate_approvable_revision
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin
from app.media.reference_fence import fence_platform_revision_media_write
from app.publishing.models import Destination, PublishJob
from app.stories.models import StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision

logger = logging.getLogger(__name__)


async def enqueue_telegram_publish_intent(
    session: Any,
    *,
    revision: PlatformVariantRevision,
    destination: Destination,
    dispatch: AutomationDispatch | None = None,
) -> PublishJob:
    """Create the durable publish intent without contacting Telegram.

    Until Task 8 renders destination-specific operations, ``payload_hash`` is the
    exact revision content/evidence hash. Task 9 replaces it with the verified
    rendered-plan hash before any remote dispatch.
    """

    try:
        validate_approvable_revision(revision)
    except RevisionValidationError as exc:
        raise NeedsReviewJobError(
            code="telegram_revision_validation_invalid",
            message=str(exc),
        ) from None

    idempotency_key = f"telegram-publish:{destination.id}:{revision.id}:{revision.content_hash}"
    publish_job = await session.scalar(
        select(PublishJob).where(PublishJob.idempotency_key == idempotency_key).with_for_update()
    )
    if publish_job is None:
        publish_job = PublishJob(
            destination_id=destination.id,
            platform_variant_revision_id=revision.id,
            status="queued",
            idempotency_key=idempotency_key,
            payload_hash=revision.content_hash,
        )
        try:
            async with session.begin_nested():
                session.add(publish_job)
                await session.flush()
        except IntegrityError:
            publish_job = await session.scalar(
                select(PublishJob).where(PublishJob.idempotency_key == idempotency_key).with_for_update()
            )
            if publish_job is None:  # pragma: no cover - unique conflict guarantees it
                raise
    enqueue = await JobRepository(session).enqueue_job(
        job_type="telegram.publish",
        payload={"publish_job_id": str(publish_job.id)},
        idempotency_key=idempotency_key,
        origin=JobOrigin.AUTOMATION,
        pause_sensitive=True,
    )
    publish_job.workflow_job_id = enqueue.job.id
    if dispatch is not None:
        dispatch.publish_job_id = publish_job.id
    session.add(
        WorkflowEvent(
            workflow_job_id=enqueue.job.id,
            event_type="telegram.publish.requested",
            actor="automation",
            event_data=redact_event_data(
                {
                    "publish_job_id": str(publish_job.id),
                    "destination_id": str(destination.id),
                    "revision_id": str(revision.id),
                    "content_hash": revision.content_hash,
                }
            ),
        )
    )
    await session.flush()
    return publish_job


async def _exact_dispatch_evidence(
    session: Any,
    story_revision_id: UUID,
) -> StoryEvidenceSnapshot:
    links = list(
        await session.scalars(
            select(StoryEvidenceLink).where(
                StoryEvidenceLink.story_revision_id == story_revision_id,
                StoryEvidenceLink.claim_key == "telegram.source",
            )
        )
    )
    if len(links) != 1:
        raise NeedsReviewJobError(
            code="telegram_evidence_ambiguous",
            message="Captured Telegram evidence is missing or ambiguous",
        )
    snapshot = await session.get(StoryEvidenceSnapshot, links[0].evidence_snapshot_id)
    if snapshot is None:
        raise NeedsReviewJobError(
            code="telegram_evidence_missing",
            message="Captured Telegram evidence is missing",
        )
    try:
        validate_evidence_snapshot(snapshot)
    except ValueError as exc:
        raise NeedsReviewJobError(
            code="telegram_evidence_invalid",
            message=str(exc),
        ) from None
    return snapshot


async def _dispatch_media(
    session: Any,
    source_item: SourceItem,
    *,
    lock_for_revision: bool = True,
) -> tuple[ContentItem, tuple[MediaAsset, ...]]:
    if source_item.content_item_id is None:
        raise NeedsReviewJobError(
            code="telegram_content_missing",
            message="Captured Telegram content item is missing",
        )
    content_item = await session.get(ContentItem, source_item.content_item_id)
    if content_item is None:
        raise NeedsReviewJobError(
            code="telegram_content_missing",
            message="Captured Telegram content item is missing",
        )
    media_statement = (
        select(MediaAsset)
        .join(ItemMedia, ItemMedia.media_asset_id == MediaAsset.id)
        .where(ItemMedia.content_item_id == content_item.id)
        .order_by(ItemMedia.sort_order, MediaAsset.created_at, MediaAsset.id)
    )
    if lock_for_revision:
        await fence_platform_revision_media_write(session)
        media_statement = media_statement.with_for_update(of=MediaAsset).execution_options(populate_existing=True)
    media = tuple(await session.scalars(media_statement))
    return content_item, media


def _media_decision(route: AutomationRoute, media: tuple[MediaAsset, ...]) -> tuple[list[UUID], bool, str | None]:
    decision = evaluate_media_policy(route.media_policy, media)
    if decision.terminal_reason == "media_expired":
        raise NeedsReviewJobError(
            code="telegram_media_expired",
            message="Captured Telegram media expired before revision persistence",
        )
    return list(decision.media_asset_ids), decision.ready, decision.reason


async def _route_parent_revision(
    session: Any,
    *,
    dispatch: AutomationDispatch,
    story_id: UUID,
) -> PlatformVariantRevision | None:
    return await session.scalar(
        select(PlatformVariantRevision)
        .join(
            AutomationDispatch,
            AutomationDispatch.variant_revision_id == PlatformVariantRevision.id,
        )
        .join(StoryRevision, StoryRevision.id == AutomationDispatch.story_revision_id)
        .where(
            AutomationDispatch.route_id == dispatch.route_id,
            AutomationDispatch.id != dispatch.id,
            AutomationDispatch.variant_revision_id.is_not(None),
            StoryRevision.story_id == story_id,
            AutomationDispatch.creation_sequence < dispatch.creation_sequence,
        )
        .order_by(
            AutomationDispatch.creation_sequence.desc(),
            PlatformVariantRevision.revision_number.desc(),
        )
        .limit(1)
        .execution_options(populate_existing=True)
    )


async def _content_pack_and_variant(
    session: Any,
    *,
    dispatch: AutomationDispatch,
    route: AutomationRoute,
    story_revision: StoryRevision,
    parent: PlatformVariantRevision | None,
) -> tuple[ContentPack, PlatformVariant]:
    if parent is not None:
        variant = await session.scalar(
            select(PlatformVariant).where(PlatformVariant.id == parent.platform_variant_id).with_for_update()
        )
        if variant is None:
            raise NeedsReviewJobError(
                code="telegram_lineage_invalid",
                message="Telegram revision lineage is invalid",
            )
        pack = await session.get(ContentPack, variant.content_pack_id)
        if pack is None:
            raise NeedsReviewJobError(
                code="telegram_lineage_invalid",
                message="Telegram content pack is missing",
            )
        return pack, variant

    pack = await session.scalar(
        select(ContentPack)
        .where(
            ContentPack.story_revision_id == story_revision.id,
            ContentPack.brand_profile_id == route.brand_profile_id,
        )
        .with_for_update()
    )
    if pack is None:
        candidate = ContentPack(
            story_revision_id=story_revision.id,
            brand_profile_id=route.brand_profile_id,
            status="draft",
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
            pack = candidate
        except IntegrityError:
            pack = await session.scalar(
                select(ContentPack)
                .where(
                    ContentPack.story_revision_id == story_revision.id,
                    ContentPack.brand_profile_id == route.brand_profile_id,
                )
                .with_for_update()
            )
            if pack is None:  # pragma: no cover
                raise
    variant = await session.scalar(
        select(PlatformVariant)
        .where(
            PlatformVariant.content_pack_id == pack.id,
            PlatformVariant.platform == "telegram",
        )
        .with_for_update()
    )
    if variant is None:
        candidate_variant = PlatformVariant(content_pack_id=pack.id, platform="telegram")
        try:
            async with session.begin_nested():
                session.add(candidate_variant)
                await session.flush()
            variant = candidate_variant
        except IntegrityError:
            variant = await session.scalar(
                select(PlatformVariant)
                .where(
                    PlatformVariant.content_pack_id == pack.id,
                    PlatformVariant.platform == "telegram",
                )
                .with_for_update()
            )
            if variant is None:  # pragma: no cover
                raise
    variant = await session.scalar(select(PlatformVariant).where(PlatformVariant.id == variant.id).with_for_update())
    if variant is None:  # pragma: no cover
        raise RuntimeError("Telegram variant disappeared during allocation")
    return pack, variant


async def _require_automation_variant_write_allowed(session: Any, variant_id: UUID) -> None:
    try:
        await require_revision_write_allowed(session, variant_id=variant_id)
    except RegenerationFenceConflict:
        raise RetryableJobError(
            code="telegram_variant_regeneration_in_progress",
            message="Telegram variant regeneration is in progress",
        ) from None


def _generation_error(exc: Exception, route: AutomationRoute, job: JobExecution) -> Exception:
    if isinstance(exc, OpenRouterRetryableError):
        scheduled = retry_at(
            route.retry_policy or {},
            attempt_number=max(1, job.attempt_count),
            now=datetime.now(UTC),
        )
        if scheduled is None:
            return NeedsReviewJobError(
                code="telegram_generation_retries_exhausted",
                message="Telegram generation requires operator attention",
            )
        return RetryableJobError(code=exc.code, message=str(exc), retry_at=scheduled)
    if isinstance(exc, OpenRouterNeedsReviewError):
        return NeedsReviewJobError(code=exc.code, message=str(exc))
    if isinstance(exc, ValidationError):
        return NeedsReviewJobError(
            code="telegram_generation_output_invalid",
            message="Generated Telegram output failed validation",
        )
    if isinstance(exc, (OpenRouterPermanentError, ProviderProfileConfigurationError)):
        return PermanentJobError(
            code=getattr(exc, "code", "telegram_provider_configuration_invalid"),
            message=str(exc),
        )
    return exc


async def _resolve_process_prompt(
    session: Any,
    *,
    route: AutomationRoute,
    payload: ProcessDispatchPayload,
    workflow_job_id: UUID,
) -> PromptTemplateVersion:
    if payload.prompt_template_version_id is not None:
        prompt = await session.get(
            PromptTemplateVersion,
            payload.prompt_template_version_id,
        )
        if (
            prompt is None
            or prompt.checksum_sha256 != payload.prompt_checksum
            or (route.prompt_policy != "follow_active" and prompt.id != route.prompt_template_version_id)
        ):
            raise NeedsReviewJobError(
                code="telegram_prompt_snapshot_invalid",
                message="Telegram prompt snapshot is missing or changed",
            )
    elif route.prompt_policy == "follow_active":
        templates = list(
            await session.scalars(select(PromptTemplate).where(PromptTemplate.purpose_key == "telegram_rewrite"))
        )
        template_ids = {item.id for item in templates}
        candidates = list(
            await session.scalars(
                select(PromptTemplateVersion).where(
                    PromptTemplateVersion.prompt_template_id.in_(template_ids),
                    PromptTemplateVersion.is_active.is_(True),
                )
            )
        )
        active = [item for item in candidates if item.prompt_template_id in template_ids and item.is_active]
        if len(active) != 1:
            raise NeedsReviewJobError(
                code="telegram_active_prompt_invalid",
                message="Telegram active prompt configuration is invalid",
            )
        prompt = active[0]
    else:
        prompt = await session.get(
            PromptTemplateVersion,
            route.prompt_template_version_id,
        )
        if prompt is None:
            raise PermanentJobError(
                code="telegram_prompt_missing",
                message="Pinned Telegram prompt version was not found",
            )

    if payload.prompt_template_version_id is None:
        stored_job = await session.get(WorkflowJob, workflow_job_id)
        if stored_job is not None:
            stored_job.payload = {
                **dict(stored_job.payload or {}),
                "prompt_template_version_id": str(prompt.id),
                "prompt_checksum": prompt.checksum_sha256,
            }
    return prompt
