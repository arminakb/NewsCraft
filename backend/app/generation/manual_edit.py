from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.automations.telegram.handlers import sha256_canonical
from app.db.models import ItemMedia, MediaAsset, SourceItem
from app.generation.commands import EditVariantRequest
from app.generation.errors import InvalidGenerationRequest, RevisionConflict
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.generation.multiplatform import ordered_distinct_citations, payload_claims
from app.generation.platform_media import trusted_story_media, validate_payload_media_assignments
from app.generation.platform_schemas import ManualPlatformEditRequest
from app.generation.platform_validation import revision_gates_from_issues, validate_platform_payload
from app.generation.revision_fence import RegenerationFenceConflict, require_revision_write_allowed
from app.generation.telegram_schema import TelegramEvidenceCitation, TelegramVariantContent
from app.media.reference_fence import fence_platform_revision_media_write
from app.research.citations import CitationIntegrityError, validate_citations
from app.research.schemas import CitationRef, Claim
from app.stories.evidence import EvidenceRecord
from app.stories.models import StoryEvidenceSnapshot


def _edit_request(request: EditVariantRequest | None, kwargs: dict[str, Any]) -> EditVariantRequest:
    if request is not None:
        return request
    return EditVariantRequest(
        base_revision_id=kwargs["base_revision_id"],
        base_content_hash=kwargs["base_content_hash"],
        content=kwargs["content"],
        media_asset_ids=kwargs["media_asset_ids"],
        edit_note=kwargs["edit_note"],
    )


async def _locked_telegram_parent(
    service: Any,
    variant_id: UUID,
    request: EditVariantRequest,
) -> tuple[PlatformVariant, PlatformVariantRevision]:
    variant = await service.session.scalar(
        select(PlatformVariant).where(PlatformVariant.id == variant_id).with_for_update()
    )
    if variant is None:
        raise RevisionConflict("base revision not found")
    if variant.platform != "telegram":
        raise RevisionConflict("platform conflicts with Telegram edit")
    try:
        await require_revision_write_allowed(service.session, variant_id=variant.id)
    except RegenerationFenceConflict:
        raise RevisionConflict("variant regeneration is in progress") from None
    parent = await service.session.scalar(
        select(PlatformVariantRevision)
        .where(
            PlatformVariantRevision.id == request.base_revision_id,
            PlatformVariantRevision.platform_variant_id == variant_id,
        )
        .with_for_update()
    )
    if parent is None:
        raise RevisionConflict("base revision not found")
    if parent.content_hash != request.base_content_hash:
        raise RevisionConflict("content hash changed")
    return variant, parent


async def _telegram_evidence(
    service: Any,
    variant: PlatformVariant,
    parent: PlatformVariantRevision,
) -> list[TelegramEvidenceCitation]:
    story_revision = await service._pack_story_revision(variant)
    citations = [TelegramEvidenceCitation.model_validate(item) for item in parent.evidence_map or []]
    if not citations:
        raise InvalidGenerationRequest("revision evidence map is empty")
    snapshots = list(
        await service.session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_([item.evidence_snapshot_id for item in citations]),
                StoryEvidenceSnapshot.story_id == story_revision.story_id,
            )
        )
    )
    if {item.id for item in snapshots} != {item.evidence_snapshot_id for item in citations}:
        raise InvalidGenerationRequest("revision evidence snapshot is missing")
    records = {
        item.id: EvidenceRecord(
            evidence_key=item.evidence_key,
            evidence_snapshot_id=item.id,
            content_item_id=item.content_item_id,
            title=item.title,
            content_text=item.content_text,
            content_sha256=item.content_sha256,
            source_url=item.source_url,
            authors=tuple(item.authors or []),
            published_at=item.published_at,
            captured_at=item.captured_at,
        )
        for item in snapshots
    }
    try:
        claims = [
            Claim(
                text="Preserved Telegram evidence",
                citations=[CitationRef.model_validate(item.model_dump())],
            )
            for item in citations
        ]
        validate_citations(claims, records)
    except ValueError:
        raise InvalidGenerationRequest("revision evidence no longer matches") from None
    return citations


async def _validate_telegram_media(
    service: Any,
    parent_content: TelegramVariantContent,
    media_asset_ids: list[UUID],
) -> None:
    requested = set(media_asset_ids)
    if len(requested) != len(media_asset_ids):
        raise InvalidGenerationRequest("media asset IDs must be unique")
    if parent_content.media_policy == "omit" and requested:
        raise InvalidGenerationRequest("omit-media revisions cannot attach media")
    if requested:
        await _require_verified_media(service, requested)
    if parent_content.media_policy == "preserve":
        await _require_source_media(service, parent_content, requested)


async def _require_verified_media(service: Any, requested: set[UUID]) -> None:
    await fence_platform_revision_media_write(service.session)
    media_assets = list(
        await service.session.scalars(
            select(MediaAsset)
            .where(MediaAsset.id.in_(requested))
            .order_by(MediaAsset.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if {item.id for item in media_assets} != requested:
        raise InvalidGenerationRequest("one or more media assets do not exist")
    if any(
        item.fetch_status != "downloaded" or not item.storage_path or not item.checksum_sha256 for item in media_assets
    ):
        raise InvalidGenerationRequest("media assets must be checksum-verified")


async def _require_source_media(
    service: Any,
    parent_content: TelegramVariantContent,
    requested: set[UUID],
) -> None:
    if parent_content.source_item_id is None:
        raise InvalidGenerationRequest("preserved media provenance is missing")
    source_item = await service.session.get(SourceItem, parent_content.source_item_id)
    if source_item is None or source_item.content_item_id is None:
        raise InvalidGenerationRequest("preserved media provenance is invalid")
    linked_ids = set(
        await service.session.scalars(
            select(ItemMedia.media_asset_id).where(ItemMedia.content_item_id == source_item.content_item_id)
        )
    )
    if not requested.issubset(linked_ids):
        raise InvalidGenerationRequest("preserved media must belong to the source")


async def _create_telegram_revision(
    service: Any,
    variant_id: UUID,
    parent: PlatformVariantRevision,
    request: EditVariantRequest,
    citations: list[TelegramEvidenceCitation],
    parent_content: TelegramVariantContent,
) -> PlatformVariantRevision:
    content = TelegramVariantContent(
        body=request.content.body,
        parse_mode=request.content.parse_mode,
        buttons=request.content.buttons,
        source_item_id=parent_content.source_item_id,
        source_url=parent_content.source_url,
        media_policy=parent_content.media_policy,
        media_asset_ids=request.media_asset_ids,
        direction=parent_content.direction,
        dry_run=parent_content.dry_run,
    ).model_dump(mode="json")
    evidence_map = [item.model_dump(mode="json") for item in citations]
    next_number = (
        int(
            await service.session.scalar(
                select(func.coalesce(func.max(PlatformVariantRevision.revision_number), 0)).where(
                    PlatformVariantRevision.platform_variant_id == variant_id
                )
            )
            or 0
        )
        + 1
    )
    child = PlatformVariantRevision(
        platform_variant_id=variant_id,
        parent_revision_id=parent.id,
        generation_attempt_id=None,
        revision_number=next_number,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
        evidence_map=evidence_map,
        validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
        approval_state="pending_review",
        approval_note=request.edit_note,
        created_by="operator",
    )
    service.session.add(child)
    await service.session.flush()
    return child


async def edit_variant(
    service: Any,
    variant_id: UUID,
    request: EditVariantRequest | None = None,
    **kwargs: Any,
) -> PlatformVariantRevision:
    edit = _edit_request(request, kwargs)
    variant, parent = await _locked_telegram_parent(service, variant_id, edit)
    citations = await _telegram_evidence(service, variant, parent)
    parent_content = TelegramVariantContent.model_validate(parent.content)
    await _validate_telegram_media(service, parent_content, edit.media_asset_ids)
    return await _create_telegram_revision(
        service,
        variant_id,
        parent,
        edit,
        citations,
        parent_content,
    )


async def edit_manual_platform_variant(
    service: Any,
    variant_id: UUID,
    request: ManualPlatformEditRequest,
) -> PlatformVariantRevision:
    variant = await service.session.scalar(
        select(PlatformVariant).where(PlatformVariant.id == variant_id).with_for_update()
    )
    if variant is None:
        raise RevisionConflict("variant not found")
    if request.payload.platform != variant.platform:
        raise RevisionConflict("platform conflicts with target variant")
    try:
        await require_revision_write_allowed(service.session, variant_id=variant.id)
    except RegenerationFenceConflict:
        raise RevisionConflict("variant regeneration is in progress") from None
    current = await service.session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.platform_variant_id == variant_id)
        .order_by(
            PlatformVariantRevision.revision_number.desc(),
            PlatformVariantRevision.created_at.desc(),
            PlatformVariantRevision.id.desc(),
        )
        .limit(1)
        .with_for_update()
    )
    if current is None or current.id != request.base_revision_id or current.content_hash != request.base_content_hash:
        raise RevisionConflict("base revision is stale")
    payload = request.payload.content
    issues = validate_platform_payload(variant.platform, payload)
    failed = next((item for item in issues if item.severity == "error"), None)
    if failed is not None:
        raise InvalidGenerationRequest(failed.message, code=failed.code)
    expected_evidence = [item.model_dump(mode="json") for item in ordered_distinct_citations(payload)]
    supplied_evidence = [item.model_dump(mode="json") for item in request.evidence_map]
    if supplied_evidence != expected_evidence:
        raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity")
    records = await service._evidence_records(await service._pack_story_revision(variant))
    try:
        validate_citations(payload_claims(variant.platform, payload), records)
    except ValueError:
        raise InvalidGenerationRequest("citation integrity failed", code="citation_integrity") from None
    authorized_media, _projection = await trusted_story_media(
        service.session,
        records,
        lock_rows=True,
    )
    try:
        validate_payload_media_assignments(payload, authorized_media)
    except CitationIntegrityError:
        raise InvalidGenerationRequest("media integrity failed", code="media_integrity") from None
    content = payload.model_dump(mode="json")
    child = PlatformVariantRevision(
        platform_variant_id=variant.id,
        parent_revision_id=current.id,
        generation_attempt_id=None,
        revision_number=current.revision_number + 1,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": supplied_evidence}),
        evidence_map=supplied_evidence,
        validation_results=revision_gates_from_issues(issues),
        approval_state="pending_review",
        approval_note=request.edit_note,
        created_by="operator",
    )
    service.session.add(child)
    await service.session.flush()
    return child
