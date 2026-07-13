from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.stories import _story_summary
from app.api.telegram_destinations import get_secret_resolver
from app.db.session import get_session
from app.generation.editorial_service import (
    ApprovalRequest,
    EditorialService,
    EditVariantRequest,
    GeneratePackRequest,
    InvalidGenerationRequest,
    RegenerateVariantRequest,
    RevisionConflict,
)
from app.generation.models import ContentPack, PlatformVariant, PlatformVariantRevision
from app.generation.providers.profiles import ProviderProfileResolver
from app.generation.providers.registry import build_default_provider_registry
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision

router = APIRouter(tags=["content-packs"])
SessionDependency = Depends(get_session)
SecretResolverDependency = Depends(get_secret_resolver)


def get_editorial_profile_resolver(
    secrets=SecretResolverDependency,
) -> ProviderProfileResolver:
    return ProviderProfileResolver(
        secret_resolver=secrets,
        http_client_factory=lambda **kwargs: httpx.AsyncClient(
            base_url=kwargs["base_url"], timeout=kwargs["timeout_seconds"]
        ),
        provider_registry=build_default_provider_registry(),
    )


ProfileResolverDependency = Depends(get_editorial_profile_resolver)


def _revision_out(row: PlatformVariantRevision) -> dict[str, Any]:
    return {
        "id": row.id,
        "platform_variant_id": row.platform_variant_id,
        "parent_revision_id": row.parent_revision_id,
        "generation_attempt_id": row.generation_attempt_id,
        "revision_number": row.revision_number,
        "content": row.content,
        "content_hash": row.content_hash,
        "evidence_map": row.evidence_map,
        "validation_results": row.validation_results,
        "approval_state": row.approval_state,
        "approval_note": row.approval_note,
        "approved_at": row.approved_at,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


async def _pack_out(session: AsyncSession, pack: ContentPack) -> dict[str, Any]:
    variants = list(
        await session.scalars(
            select(PlatformVariant).where(PlatformVariant.content_pack_id == pack.id).order_by(PlatformVariant.platform)
        )
    )
    return {
        "id": pack.id,
        "story_revision_id": pack.story_revision_id,
        "brand_profile_id": pack.brand_profile_id,
        "status": pack.status,
        "created_at": pack.created_at,
        "updated_at": pack.updated_at,
        "variants": [{"id": item.id, "platform": item.platform} for item in variants],
    }


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RevisionConflict):
        return HTTPException(409, str(exc))
    return HTTPException(422, str(exc))


@router.get("/stories/{story_id}")
async def get_story(story_id: UUID, session: AsyncSession = SessionDependency):
    story = await session.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")
    return await _story_summary(session, story)


@router.get("/stories/{story_id}/evidence")
async def story_evidence(story_id: UUID, session: AsyncSession = SessionDependency):
    if await session.get(Story, story_id) is None:
        raise HTTPException(404, "Story not found")
    rows = list(
        await session.scalars(
            select(StoryEvidenceSnapshot)
            .where(StoryEvidenceSnapshot.story_id == story_id)
            .order_by(StoryEvidenceSnapshot.captured_at, StoryEvidenceSnapshot.id)
        )
    )
    return [
        {
            "id": row.id,
            "evidence_key": row.evidence_key,
            "title": row.title,
            "content_text": row.content_text,
            "content_sha256": row.content_sha256,
            "source_url": row.source_url,
            "authors": row.authors,
            "published_at": row.published_at,
            "captured_at": row.captured_at,
        }
        for row in rows
    ]


@router.get("/stories/{story_id}/revisions")
async def story_revisions(story_id: UUID, session: AsyncSession = SessionDependency):
    return list(
        await session.scalars(
            select(StoryRevision)
            .where(StoryRevision.story_id == story_id)
            .order_by(StoryRevision.revision_number.desc())
        )
    )


@router.post("/stories/{story_id}/content-packs", status_code=202)
async def create_content_pack(
    story_id: UUID,
    body: GeneratePackRequest,
    session: AsyncSession = SessionDependency,
    profile_resolver: ProviderProfileResolver = ProfileResolverDependency,
):
    try:
        result = await EditorialService(session, profile_resolver=profile_resolver).request_content_pack(story_id, body)
    except InvalidGenerationRequest as exc:
        raise _service_error(exc) from None
    await session.commit()
    return result


@router.get("/content-packs")
async def list_content_packs(session: AsyncSession = SessionDependency):
    rows = list(await session.scalars(select(ContentPack).order_by(ContentPack.created_at.desc())))
    return [await _pack_out(session, row) for row in rows]


@router.get("/content-packs/{pack_id}")
async def get_content_pack(pack_id: UUID, session: AsyncSession = SessionDependency):
    pack = await session.get(ContentPack, pack_id)
    if pack is None:
        raise HTTPException(404, "Content pack not found")
    return await _pack_out(session, pack)


@router.get("/platform-variants/{variant_id}/revisions")
async def list_variant_revisions(variant_id: UUID, session: AsyncSession = SessionDependency):
    rows = list(
        await session.scalars(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant_id)
            .order_by(PlatformVariantRevision.revision_number.desc())
        )
    )
    return [_revision_out(row) for row in rows]


@router.post("/platform-variants/{variant_id}/revisions", status_code=201)
async def edit_variant(variant_id: UUID, body: EditVariantRequest, session: AsyncSession = SessionDependency):
    try:
        result = await EditorialService(session).edit_variant(variant_id, body)
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise _service_error(exc) from None
    await session.commit()
    return _revision_out(result)


@router.post("/platform-variants/{variant_id}/regenerate", status_code=202)
async def regenerate_variant(
    variant_id: UUID,
    body: RegenerateVariantRequest,
    session: AsyncSession = SessionDependency,
    profile_resolver: ProviderProfileResolver = ProfileResolverDependency,
):
    try:
        result = await EditorialService(session, profile_resolver=profile_resolver).regenerate_variant(variant_id, body)
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise _service_error(exc) from None
    await session.commit()
    return result


@router.post("/platform-variant-revisions/{revision_id}/approve")
async def approve_revision(revision_id: UUID, body: ApprovalRequest, session: AsyncSession = SessionDependency):
    try:
        result = await EditorialService(session).approve_revision(revision_id, body)
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise _service_error(exc) from None
    await session.commit()
    return _revision_out(result)


@router.post("/platform-variant-revisions/{revision_id}/reject")
async def reject_revision(revision_id: UUID, body: ApprovalRequest, session: AsyncSession = SessionDependency):
    try:
        result = await EditorialService(session).reject_revision(revision_id, body)
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise _service_error(exc) from None
    await session.commit()
    return _revision_out(result)
