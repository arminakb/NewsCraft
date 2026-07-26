from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.automations.telegram.handlers import sha256_canonical
from app.generation.commands import ApprovalRequest
from app.generation.errors import InvalidGenerationRequest, RevisionConflict
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.platform_schemas import TelegramVariantPayload
from app.generation.platform_validation import validate_platform_payload
from app.generation.revision_validation import RevisionValidationError, validate_approvable_revision
from app.workflows.states import ContentPackState, require_content_pack_transition, require_variant_approval_transition


async def approve_revision(
    service: Any, revision_id: UUID, request: ApprovalRequest | None = None, **kwargs: Any
) -> PlatformVariantRevision:
    if request is None:
        request = ApprovalRequest(expected_content_hash=kwargs["expected_content_hash"], note=kwargs.get("note"))
    revision, variant = await _locked_approvable_revision(service, revision_id, request)
    await _validate_revision(service, variant, revision)
    await _require_current_revision(service, revision)
    revision.approval_state = require_variant_approval_transition(revision.approval_state, "approved")
    revision.approval_note = request.note
    revision.approved_at = datetime.now(UTC)
    service._event("content_pack.revision.approved", revision)
    await service.session.flush()
    await _refresh_pack_status(service, variant.content_pack_id)
    return revision


async def _locked_approvable_revision(
    service: Any,
    revision_id: UUID,
    request: ApprovalRequest,
) -> tuple[PlatformVariantRevision, PlatformVariant]:
    revision = await service.session.scalar(
        select(PlatformVariantRevision).where(PlatformVariantRevision.id == revision_id).with_for_update()
    )
    if revision is None:
        raise RevisionConflict("revision not found")
    if revision.content_hash != request.expected_content_hash:
        raise RevisionConflict("content hash changed")
    if revision.content_hash != sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map}):
        raise InvalidGenerationRequest(
            "stored revision content hash is invalid",
            code="content_integrity",
        )
    if revision.approval_state != "pending_review":
        raise RevisionConflict("revision is not pending review")
    if not revision.evidence_map:
        raise InvalidGenerationRequest("Revision evidence map is empty")
    variant = await service.session.get(PlatformVariant, revision.platform_variant_id)
    if variant is None:
        raise RevisionConflict("variant not found")
    return revision, variant


async def _validate_revision(
    service: Any,
    variant: PlatformVariant,
    revision: PlatformVariantRevision,
) -> None:
    if variant.platform == "telegram":
        try:
            validate_approvable_revision(revision)
            telegram_payload = TelegramVariantPayload.model_validate(revision.content)
            issues = validate_platform_payload("telegram", telegram_payload)
            failed = next((item for item in issues if item.severity == "error"), None)
            if failed is not None:
                raise InvalidGenerationRequest(failed.message, code=failed.code)
            await service._validate_telegram_revision_evidence(revision)
        except (RevisionValidationError, InvalidGenerationRequest) as exc:
            raise InvalidGenerationRequest(str(exc), code=getattr(exc, "code", None)) from None
    else:
        await service._revalidate_manual_revision(variant, revision)


async def _require_current_revision(service: Any, revision: PlatformVariantRevision) -> None:
    latest_id = await service.session.scalar(
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
        raise RevisionConflict("revision is not current")


async def reject_revision(service: Any, revision_id: UUID, request: ApprovalRequest) -> PlatformVariantRevision:
    revision = await service.session.scalar(
        select(PlatformVariantRevision).where(PlatformVariantRevision.id == revision_id).with_for_update()
    )
    if revision is None or revision.content_hash != request.expected_content_hash:
        raise RevisionConflict("content hash changed")
    if revision.approval_state != "pending_review":
        raise RevisionConflict("revision is not pending review")
    revision.approval_state = require_variant_approval_transition(revision.approval_state, "rejected")
    revision.approval_note = request.note
    revision.approved_at = None
    service._event("content_pack.revision.rejected", revision)
    await service.session.flush()
    variant = await service.session.get(PlatformVariant, revision.platform_variant_id)
    if variant is not None:
        await _refresh_pack_status(service, variant.content_pack_id)
    return revision


async def _refresh_pack_status(service: Any, pack_id: UUID) -> None:
    pack = await service.session.scalar(select(ContentPack).where(ContentPack.id == pack_id).with_for_update())
    if pack is None:
        raise RevisionConflict("content pack not found")
    variants = list(
        await service.session.scalars(
            select(PlatformVariant).where(PlatformVariant.content_pack_id == pack_id).order_by(PlatformVariant.id)
        )
    )
    current_states: list[str] = []
    for variant in variants:
        state = await service.session.scalar(
            select(PlatformVariantRevision.approval_state)
            .where(PlatformVariantRevision.platform_variant_id == variant.id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
        )
        if state is not None:
            current_states.append(state)
    target: ContentPackState = (
        "ready"
        if variants and len(current_states) == len(variants) and all(state == "approved" for state in current_states)
        else "draft"
    )
    if pack.status != target:
        pack.status = require_content_pack_transition(pack.status, target)
        await service.session.flush()
