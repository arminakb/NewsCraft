from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.stories import _story_summary
from app.api.telegram_destinations import get_secret_resolver
from app.core.redaction import redact_secrets
from app.db.session import get_session
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
    AIProviderProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplateVersion,
)
from app.generation.multiplatform import PLATFORM_ORDER
from app.generation.platform_media import trusted_story_media
from app.generation.platform_schemas import (
    BlogVariantPayload,
    InstagramVariantPayload,
    ManualPlatformEditRequest,
    TelegramVariantPayload,
    XVariantPayload,
)
from app.generation.platform_validation import validate_platform_payload
from app.generation.providers.profiles import ProviderProfileResolver
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.models import WorkflowJob
from app.research.schemas import CitationRef
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision

router = APIRouter(tags=["content-packs"])
SessionDependency = Depends(get_session)
SecretResolverDependency = Depends(get_secret_resolver)


class RenderedRevisionHtmlOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision_id: UUID
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform: Literal["blog"]
    html: str = Field(min_length=1)


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


def _platform_values(rows: Any) -> set[str]:
    return {
        value
        for row in rows
        if isinstance((value := getattr(row, "platform", row)), str)
    }


async def _pack_has_exact_current_platforms(
    session: AsyncSession,
    pack_id: UUID,
    expected_platforms: list[str],
) -> bool:
    variants = list(
        await session.scalars(
            select(PlatformVariant).where(PlatformVariant.content_pack_id == pack_id)
        )
    )
    if _platform_values(variants) != set(expected_platforms) or len(variants) != len(expected_platforms):
        return False
    for variant in variants:
        current_revision_id = await session.scalar(
            select(PlatformVariantRevision.id)
            .where(PlatformVariantRevision.platform_variant_id == variant.id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
        )
        if current_revision_id is None:
            return False
    return True


def _validation_path(code: str) -> str:
    for marker, path in (
        ("caption", "caption"),
        ("hashtag", "hashtags"),
        ("carousel", "carousel"),
        ("seo_description", "seo_description"),
        ("canonical_sources", "canonical_sources"),
        ("hero", "hero_media"),
        ("checklist", "manual_checklist"),
        ("post", "posts"),
        ("media", "media"),
    ):
        if marker in code:
            return path
    return "content"


def _media_plan(platform: str | None, content: dict[str, Any]) -> list[Any]:
    if platform == "telegram":
        return list(content.get("media_asset_ids") or [])
    if platform == "instagram":
        return [slide.get("media") for slide in content.get("carousel", []) if isinstance(slide, dict)]
    if platform == "x":
        return [
            media
            for post in content.get("posts", [])
            if isinstance(post, dict)
            for media in post.get("media", [])
        ]
    if platform == "blog" and content.get("hero_media") is not None:
        return [content["hero_media"]]
    return []


async def _source_media_out(
    session: AsyncSession,
    story_revision: StoryRevision | Any | None,
) -> list[dict[str, Any]]:
    raw_citations = getattr(story_revision, "citations", None)
    if not raw_citations:
        return []
    try:
        citations = [CitationRef.model_validate(item) for item in raw_citations]
    except (TypeError, ValueError):
        return []
    snapshot_ids = {item.evidence_snapshot_id for item in citations}
    if not snapshot_ids:
        return []
    snapshots = list(
        await session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_(snapshot_ids),
                StoryEvidenceSnapshot.story_id == story_revision.story_id,
            )
        )
    )
    _authorized, projection = await trusted_story_media(
        session,
        {snapshot.id: snapshot for snapshot in snapshots},
    )
    return projection


async def _revision_out(session: AsyncSession, row: PlatformVariantRevision) -> dict[str, Any]:
    variant = await session.get(PlatformVariant, row.platform_variant_id)
    pack = await session.get(ContentPack, variant.content_pack_id) if variant is not None else None
    story_revision = await session.get(StoryRevision, pack.story_revision_id) if pack is not None else None
    attempt = await session.get(GenerationAttempt, row.generation_attempt_id) if row.generation_attempt_id else None
    run = await session.get(GenerationRun, attempt.generation_run_id) if attempt is not None else None
    prompt = (
        await session.get(PromptTemplateVersion, run.prompt_template_version_id)
        if run is not None and run.prompt_template_version_id
        else None
    )
    profile = (
        await session.get(AIProviderProfile, run.provider_profile_id)
        if run is not None and run.provider_profile_id
        else None
    )
    origin = (
        "automation"
        if row.created_by.startswith("automation:")
        else row.created_by
        if row.created_by in {"operator", "automation", "generation"}
        else "operator"
    )
    validation_issues: list[dict[str, Any]] = []
    payload_types = {
        "telegram": TelegramVariantPayload,
        "instagram": InstagramVariantPayload,
        "x": XVariantPayload,
        "blog": BlogVariantPayload,
    }
    if variant is not None and variant.platform in payload_types:
        try:
            platform_payload = payload_types[variant.platform].model_validate(row.content)
            validation_issues = [
                issue.model_dump(mode="json")
                for issue in validate_platform_payload(variant.platform, platform_payload)
            ]
        except ValueError:
            validation_issues = [
                {
                    "code": str(gate.get("gate") or "platform_schema_invalid"),
                    "path": _validation_path(str(gate.get("gate") or "")),
                    "message": str(gate.get("reason") or "Stored platform content is invalid"),
                    "severity": "warning" if gate.get("ok") else "error",
                }
                for gate in row.validation_results
            ] or [
                {
                    "code": "platform_schema_invalid",
                    "path": "content",
                    "message": "Stored platform content is invalid",
                    "severity": "error",
                }
            ]
    platform = variant.platform if variant is not None else None
    manual_checklist = (
        list(row.content.get("manual_checklist") or [])
        if platform in {"instagram", "x", "blog"}
        else []
    )
    source_media = await _source_media_out(session, story_revision)
    return {
        "id": row.id,
        "platform": platform,
        "platform_variant_id": row.platform_variant_id,
        "content_pack_id": pack.id if pack is not None else None,
        "story_id": story_revision.story_id if story_revision is not None else None,
        "parent_revision_id": row.parent_revision_id,
        "generation_attempt_id": row.generation_attempt_id,
        "revision_number": row.revision_number,
        "content": row.content,
        "content_hash": row.content_hash,
        "evidence_map": row.evidence_map,
        "manual_checklist": manual_checklist,
        "validation_results": row.validation_results,
        "validation_issues": validation_issues,
        "media_plan": _media_plan(variant.platform if variant is not None else None, row.content),
        "source_media": source_media,
        "approval_state": row.approval_state,
        "approval_note": row.approval_note,
        "approved_at": row.approved_at,
        "created_by": row.created_by,
        "origin": origin,
        "provider_profile": (
            {"id": profile.id, "name": profile.name, "provider_type": profile.provider_type}
            if profile is not None
            else None
        ),
        "resolved_model": attempt.resolved_model if attempt is not None else None,
        "prompt_version": (
            {
                "id": prompt.id,
                "version": prompt.version,
                "output_schema_version": prompt.output_schema_version,
                "checksum_sha256": prompt.checksum_sha256,
            }
            if prompt is not None
            else None
        ),
        "created_at": row.created_at,
    }


async def _pack_out(session: AsyncSession, pack: ContentPack) -> dict[str, Any]:
    story_revision = await session.get(StoryRevision, pack.story_revision_id)
    variants = list(
        await session.scalars(
            select(PlatformVariant).where(PlatformVariant.content_pack_id == pack.id)
        )
    )
    order = {platform: index for index, platform in enumerate(PLATFORM_ORDER)}
    variants.sort(key=lambda item: (order.get(item.platform, len(order)), str(item.id)))
    projected = []
    for item in variants:
        current = await session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == item.id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
        )
        projected.append(
            {
                "id": item.id,
                "platform": item.platform,
                "current_revision": (
                    await _revision_out(session, current)
                    if isinstance(current, PlatformVariantRevision)
                    else None
                ),
            }
        )
    return {
        "id": pack.id,
        "story_id": story_revision.story_id if story_revision is not None else None,
        "story_revision_id": pack.story_revision_id,
        "brand_profile_id": pack.brand_profile_id,
        "status": pack.status,
        "created_at": pack.created_at,
        "updated_at": pack.updated_at,
        "variants": projected,
    }


async def _request_out(session: AsyncSession, job: WorkflowJob) -> dict[str, Any] | None:
    payload = dict(job.payload or {})
    try:
        story_id = UUID(str(payload["story_id"]))
    except KeyError, TypeError, ValueError:
        return None
    try:
        expected_brand_id = UUID(str(payload["brand_profile_id"]))
    except KeyError, TypeError, ValueError:
        expected_brand_id = None
    raw_platforms = payload.get("platforms")
    expected_platforms = (
        list(dict.fromkeys(raw_platforms))
        if isinstance(raw_platforms, list) and all(item in PLATFORM_ORDER for item in raw_platforms)
        else [payload["platform"]]
        if payload.get("platform") in PLATFORM_ORDER
        else []
    )
    pack = None
    child = None
    result_revision_id = (job.result or {}).get("story_revision_id")
    if result_revision_id is not None:
        try:
            revision_id = UUID(str(result_revision_id))
        except TypeError, ValueError:
            revision_id = None
        if revision_id is not None:
            child_id = (job.result or {}).get("continuation_job_id")
            try:
                parsed_child_id = UUID(str(child_id))
            except TypeError, ValueError:
                parsed_child_id = None
            candidate = await session.get(WorkflowJob, parsed_child_id) if parsed_child_id is not None else None
            candidate_payload = dict(candidate.payload or {}) if candidate is not None else {}
            if (
                candidate is not None
                and expected_brand_id is not None
                and candidate.job_type == "content_pack.generate_telegram"
                and candidate_payload.get("story_revision_id") == str(revision_id)
                and candidate_payload.get("brand_profile_id") == str(expected_brand_id)
                and (
                    candidate_payload.get("platforms") == expected_platforms
                    or (
                        expected_platforms == ["telegram"]
                        and candidate_payload.get("platform") == "telegram"
                    )
                )
                and (candidate.idempotency_key or "").startswith(f"content-pack-telegram:{job.id}:")
            ):
                child = candidate
                child_pack_id = (candidate.result or {}).get("content_pack_id")
                try:
                    parsed_pack_id = UUID(str(child_pack_id))
                except TypeError, ValueError:
                    parsed_pack_id = None
                if parsed_pack_id is not None:
                    pack = await session.get(ContentPack, parsed_pack_id)
                    if pack is not None and (
                        pack.story_revision_id != revision_id or pack.brand_profile_id != expected_brand_id
                    ):
                        pack = None
                if candidate.status == "succeeded":
                    if pack is None:
                        pack = await session.scalar(
                            select(ContentPack)
                            .join(PlatformVariant, PlatformVariant.content_pack_id == ContentPack.id)
                            .where(
                                ContentPack.story_revision_id == revision_id,
                                ContentPack.brand_profile_id == expected_brand_id,
                                PlatformVariant.platform.in_(expected_platforms),
                            )
                            .order_by(ContentPack.created_at.desc())
                            .limit(1)
                        )
                    if pack is not None and not await _pack_has_exact_current_platforms(
                        session,
                        pack.id,
                        expected_platforms,
                    ):
                        pack = None
    current_job = child or job
    missing_exact_pack = child is not None and child.status == "succeeded" and pack is None
    status = (
        "ready"
        if child is not None and child.status == "succeeded" and pack is not None
        else "needs_review"
        if missing_exact_pack
        else current_job.status
    )
    last_failure = (
        (
            "Succeeded child did not produce an exact Telegram content pack"
            if expected_platforms == ["telegram"]
            else "Succeeded child did not produce the exact requested content pack"
        )
        if missing_exact_pack
        else str(redact_secrets(current_job.error_message))
        if current_job.status in {"failed", "needs_review", "retrying"} and current_job.error_message
        else None
    )
    return {
        "id": job.id,
        "job_id": current_job.id,
        "story_id": story_id,
        "status": status,
        "last_failure": last_failure,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "pack": await _pack_out(session, pack) if pack is not None else None,
    }


def _research_request_out(job: WorkflowJob) -> list[dict[str, Any]]:
    if job.status == "succeeded":
        return []
    rows = []
    for descriptor in (job.payload or {}).get("continuations", []):
        if not isinstance(descriptor, dict) or descriptor.get("job_type") != "content_pack.generate":
            continue
        payload = descriptor.get("payload")
        try:
            story_id = UUID(str(payload["story_id"]))
        except KeyError, TypeError, ValueError:
            continue
        rows.append(
            {
                "id": f"{job.id}:{descriptor.get('subscriber_id', story_id)}",
                "job_id": job.id,
                "story_id": story_id,
                "status": job.status,
                "last_failure": str(redact_secrets(job.error_message))
                if job.status in {"failed", "needs_review"} and job.error_message
                else None,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "pack": None,
            }
        )
    return rows


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RevisionConflict):
        return HTTPException(409, str(exc))
    code = getattr(exc, "code", None)
    return HTTPException(422, {"code": code, "message": str(exc)} if code else str(exc))


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


@router.get("/content-pack-requests")
async def list_content_pack_requests(session: AsyncSession = SessionDependency):
    jobs = list(
        await session.scalars(
            select(WorkflowJob)
            .where(WorkflowJob.job_type.in_(("content_pack.generate", "research_story")))
            .order_by(WorkflowJob.created_at.desc())
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
    packs = list(await session.scalars(select(ContentPack).order_by(ContentPack.created_at.desc())))
    for pack in packs:
        if pack.id in associated_pack_ids:
            continue
        story_revision = await session.get(StoryRevision, pack.story_revision_id)
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
                "pack": await _pack_out(session, pack),
            }
        )
    return output


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
    return [await _revision_out(session, row) for row in rows]


@router.get("/platform-variant-revisions/{revision_id}")
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


@router.post("/platform-variants/{variant_id}/revisions", status_code=201)
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
        raise _service_error(exc) from None
    await session.commit()
    return await _revision_out(session, result)


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
    return await _revision_out(session, result)


@router.post("/platform-variant-revisions/{revision_id}/reject")
async def reject_revision(revision_id: UUID, body: ApprovalRequest, session: AsyncSession = SessionDependency):
    try:
        result = await EditorialService(session).reject_revision(revision_id, body)
    except (InvalidGenerationRequest, RevisionConflict) as exc:
        raise _service_error(exc) from None
    await session.commit()
    return await _revision_out(session, result)
