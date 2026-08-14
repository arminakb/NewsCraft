from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capabilities import CapabilityStatusDependency
from app.api.content_pack_mappers import (
    ContentPackOut,
    ContentPackRequestOut,
    PlatformVariantRevisionOut,
    StoryEvidenceOut,
    StoryRevisionOut,
    StorySummaryOut,
    _pack_out,
    _packs_out,
    _prefetch_revision_graph,
    _request_out,
    _research_request_out,
    _revision_out,
)
from app.api.dependencies import SessionDependency
from app.api.editorial_errors import editorial_http_error
from app.api.stories import _story_summary
from app.automations.definitions.runtime_state import continue_automation_review
from app.exports.service import (
    ExportContractError,
    export_revision_content_hash,
    render_export_html,
)
from app.generation.editorial_service import (
    ApprovalRequest,
    EditorialService,
    EditVariantRequest,
    GeneratePackRequest,
    InvalidGenerationRequest,
    RegenerateVariantRequest,
    RevisionConflict,
)
from app.generation.models import (
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
)
from app.generation.platform_schemas import (
    ManualPlatformEditRequest,
)
from app.generation.providers.profiles import ProviderProfileResolver
from app.jobs.models import WorkflowJob
from app.jobs.schemas import JobAcceptedOut
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision

router = APIRouter(tags=["content-packs"])


class RenderedRevisionHtmlOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: Literal["blog"]
    html: str = Field(min_length=1)


def get_editorial_profile_resolver() -> None:
    """The API never constructs a provider or resolves a worker credential."""
    return None


ProfileResolverDependency = Depends(get_editorial_profile_resolver)


def _pack_summary(
    pack: ContentPack,
    story_revision: StoryRevision,
    variants: list[PlatformVariant],
) -> dict:
    return {
        "id": pack.id,
        "story_id": story_revision.story_id,
        "story_revision_id": pack.story_revision_id,
        "brand_profile_id": pack.brand_profile_id,
        "status": pack.status,
        "created_at": pack.created_at,
        "updated_at": pack.updated_at,
        "variants": [{"id": variant.id, "platform": variant.platform} for variant in variants],
    }


@router.get("/stories/{story_id}", response_model=StorySummaryOut)
async def get_story(story_id: UUID, session: AsyncSession = SessionDependency):
    story = await session.get(Story, story_id)
    if story is None:
        raise HTTPException(404, "Story not found")
    return await _story_summary(session, story)


@router.get("/stories/{story_id}/evidence", response_model=list[StoryEvidenceOut])
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


@router.get("/stories/{story_id}/revisions", response_model=list[StoryRevisionOut])
async def story_revisions(story_id: UUID, session: AsyncSession = SessionDependency):
    return list(
        await session.scalars(
            select(StoryRevision)
            .where(StoryRevision.story_id == story_id)
            .order_by(StoryRevision.revision_number.desc())
        )
    )


@router.post("/stories/{story_id}/content-packs", response_model=JobAcceptedOut, status_code=202)
async def create_content_pack(
    story_id: UUID,
    body: GeneratePackRequest,
    capability_status: CapabilityStatusDependency,
    session: AsyncSession = SessionDependency,
    profile_resolver: ProviderProfileResolver | None = ProfileResolverDependency,
):
    await capability_status.require_available(
        "provider",
        body.generation_provider_profile_id,
        "generation",
        job_type="content_pack.generate",
    )
    if body.research_mode == "auto_if_incomplete" and body.research_provider_profile_id is not None:
        await capability_status.require_available(
            "provider",
            body.research_provider_profile_id,
            "research",
            job_type="research_story",
        )
    try:
        result = await EditorialService(session, profile_resolver=profile_resolver).request_content_pack(story_id, body)
    except InvalidGenerationRequest as exc:
        raise editorial_http_error(exc) from None
    await session.commit()
    return result


# Every pack in a listing fans out into per-variant projection queries, so an
# unbounded listing degrades with the archive rather than with the page. Both
# routes answer newest-first, so the ceiling trims the tail the workspace was
# already scrolling past. Caller-visible paging would change the published
# contract and belongs with that decision, not with this bound.
LIST_CEILING = 200


@router.get("/content-packs", response_model=list[ContentPackOut])
async def list_content_packs(session: AsyncSession = SessionDependency):
    rows = list(await session.scalars(select(ContentPack).order_by(ContentPack.created_at.desc()).limit(LIST_CEILING)))
    return await _packs_out(session, rows)


@router.get("/content-pack-requests", response_model=list[ContentPackRequestOut])
async def list_content_pack_requests(session: AsyncSession = SessionDependency):
    jobs = list(
        await session.scalars(
            select(WorkflowJob)
            .where(WorkflowJob.job_type.in_(("content_pack.generate", "research_story")))
            .order_by(WorkflowJob.created_at.desc())
            .limit(LIST_CEILING)
        )
    )
    output = []
    for job in jobs:
        if job.job_type == "research_story":
            output.extend(_research_request_out(job))
        else:
            row = await _request_out(session, job)
            if row is not None:
                output.append(row)
    associated_pack_ids = {row["pack"]["id"] for row in output if row["pack"] is not None}
    packs = list(await session.scalars(select(ContentPack).order_by(ContentPack.created_at.desc()).limit(LIST_CEILING)))
    unassociated_packs = [pack for pack in packs if pack.id not in associated_pack_ids]
    if not unassociated_packs:
        return output
    story_revisions = {
        row.id: row
        for row in await session.scalars(
            select(StoryRevision).where(StoryRevision.id.in_({pack.story_revision_id for pack in unassociated_packs}))
        )
    }
    variants_by_pack: dict[UUID, list[PlatformVariant]] = {}
    for variant in await session.scalars(
        select(PlatformVariant).where(PlatformVariant.content_pack_id.in_({pack.id for pack in unassociated_packs}))
    ):
        variants_by_pack.setdefault(variant.content_pack_id, []).append(variant)
    for pack in unassociated_packs:
        story_revision = story_revisions.get(pack.story_revision_id)
        if story_revision is None:
            continue
        output.append(
            {
                "id": pack.id,
                "job_id": None,
                "story_id": story_revision.story_id,
                "status": pack.status,
                "last_failure": None,
                "created_at": pack.created_at,
                "updated_at": pack.updated_at,
                "pack": _pack_summary(pack, story_revision, variants_by_pack.get(pack.id, [])),
            }
        )
    return output


@router.get("/content-packs/{pack_id}", response_model=ContentPackOut)
async def get_content_pack(pack_id: UUID, session: AsyncSession = SessionDependency):
    pack = await session.get(ContentPack, pack_id)
    if pack is None:
        raise HTTPException(404, "Content pack not found")
    return await _pack_out(session, pack)


@router.get("/platform-variants/{variant_id}/revisions", response_model=list[PlatformVariantRevisionOut])
async def list_variant_revisions(variant_id: UUID, session: AsyncSession = SessionDependency):
    rows = list(
        await session.scalars(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant_id)
            .order_by(PlatformVariantRevision.revision_number.desc())
        )
    )
    await _prefetch_revision_graph(session, rows)
    media_cache: dict[UUID, list[dict[str, Any]]] = {}
    return [await _revision_out(session, row, media_cache) for row in rows]


@router.get("/platform-variant-revisions/{revision_id}", response_model=PlatformVariantRevisionOut)
async def get_variant_revision(revision_id: UUID, session: AsyncSession = SessionDependency):
    row = await session.get(PlatformVariantRevision, revision_id)
    if row is None:
        raise HTTPException(404, "Platform variant revision not found")
    return await _revision_out(session, row)


@router.get(
    "/platform-variant-revisions/{revision_id}/rendered-html",
    response_model=RenderedRevisionHtmlOut,
)
async def get_variant_revision_rendered_html(
    revision_id: UUID,
    session: AsyncSession = SessionDependency,
) -> RenderedRevisionHtmlOut:
    row = await session.get(PlatformVariantRevision, revision_id)
    if row is None:
        raise HTTPException(404, "Platform variant revision not found")
    variant = await session.get(PlatformVariant, row.platform_variant_id)
    if variant is None:
        raise HTTPException(404, "Platform variant not found")
    if variant.platform != "blog":
        raise HTTPException(422, "Rendered HTML projection is available only for blog revisions")
    if row.content_hash != export_revision_content_hash(row):
        raise HTTPException(409, "Revision content hash does not match its immutable content")
    try:
        html = render_export_html("blog", row.content)
    except ExportContractError as exc:
        raise HTTPException(409, str(exc)) from None
    return RenderedRevisionHtmlOut(
        revision_id=row.id,
        content_hash=row.content_hash,
        platform="blog",
        html=html,
    )


@router.post(
    "/platform-variants/{variant_id}/revisions",
    response_model=PlatformVariantRevisionOut,
    status_code=201,
)
async def edit_variant(
    variant_id: UUID,
    body: EditVariantRequest | ManualPlatformEditRequest,
    session: AsyncSession = SessionDependency,
):
    try:
        service = EditorialService(session)
        result = (
            await service.edit_manual_platform_variant(variant_id, body)
            if isinstance(body, ManualPlatformEditRequest)
            else await service.edit_variant(variant_id, body)
        )
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise editorial_http_error(exc) from None
    await session.commit()
    return await _revision_out(session, result)


@router.post(
    "/platform-variants/{variant_id}/regenerate",
    response_model=JobAcceptedOut,
    status_code=202,
)
async def regenerate_variant(
    variant_id: UUID,
    body: RegenerateVariantRequest,
    capability_status: CapabilityStatusDependency,
    session: AsyncSession = SessionDependency,
    profile_resolver: ProviderProfileResolver = ProfileResolverDependency,
):
    await capability_status.require_available(
        "provider",
        body.generation_provider_profile_id,
        "generation",
        job_type="content_pack.regenerate",
    )
    try:
        result = await EditorialService(session, profile_resolver=profile_resolver).regenerate_variant(variant_id, body)
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise editorial_http_error(exc) from None
    await session.commit()
    return result


@router.post(
    "/platform-variant-revisions/{revision_id}/approve",
    response_model=PlatformVariantRevisionOut,
)
async def approve_revision(revision_id: UUID, body: ApprovalRequest, session: AsyncSession = SessionDependency):
    try:
        result = await EditorialService(session).approve_revision(revision_id, body)
        assert result.approved_at is not None
        await continue_automation_review(
            session,
            revision_id=result.id,
            observed_at=result.approved_at,
        )
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise editorial_http_error(exc) from None
    await session.commit()
    return await _revision_out(session, result)


@router.post(
    "/platform-variant-revisions/{revision_id}/reject",
    response_model=PlatformVariantRevisionOut,
)
async def reject_revision(revision_id: UUID, body: ApprovalRequest, session: AsyncSession = SessionDependency):
    try:
        result = await EditorialService(session).reject_revision(revision_id, body)
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise editorial_http_error(exc) from None
    await session.commit()
    return await _revision_out(session, result)
