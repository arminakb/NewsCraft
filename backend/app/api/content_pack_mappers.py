from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_secrets, redact_string
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
    TelegramVariantPayload,
    XVariantPayload,
)
from app.generation.platform_validation import validate_platform_payload
from app.jobs.models import WorkflowJob
from app.research.schemas import CitationRef
from app.stories.models import StoryEvidenceSnapshot, StoryRevision


def _platform_values(rows: Any) -> set[str]:
    return {value for row in rows if isinstance((value := getattr(row, "platform", row)), str)}


async def _pack_has_exact_current_platforms(
    session: AsyncSession,
    pack_id: UUID,
    expected_platforms: list[str],
) -> bool:
    variants = list(await session.scalars(select(PlatformVariant).where(PlatformVariant.content_pack_id == pack_id)))
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
        return [media for post in content.get("posts", []) if isinstance(post, dict) for media in post.get("media", [])]
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
    except TypeError, ValueError:
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
    redacted_validation_results = redact_secrets(row.validation_results)
    validation_results = (
        [item for item in redacted_validation_results if isinstance(item, dict)]
        if isinstance(redacted_validation_results, list)
        else []
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
                issue.model_dump(mode="json") for issue in validate_platform_payload(variant.platform, platform_payload)
            ]
        except ValueError:
            validation_issues = [
                {
                    "code": str(gate.get("gate") or "platform_schema_invalid"),
                    "path": _validation_path(str(gate.get("gate") or "")),
                    "message": str(gate.get("reason") or "Stored platform content is invalid"),
                    "severity": "warning" if gate.get("ok") else "error",
                }
                for gate in validation_results
            ] or [
                {
                    "code": "platform_schema_invalid",
                    "path": "content",
                    "message": "Stored platform content is invalid",
                    "severity": "error",
                }
            ]
    platform = variant.platform if variant is not None else None
    manual_checklist = list(row.content.get("manual_checklist") or []) if platform in {"instagram", "x", "blog"} else []
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
        "validation_results": validation_results,
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
        "resolved_model": (
            redact_string(str(attempt.resolved_model))
            if attempt is not None and attempt.resolved_model is not None
            else None
        ),
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
    variants = list(await session.scalars(select(PlatformVariant).where(PlatformVariant.content_pack_id == pack.id)))
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
                    await _revision_out(session, current) if isinstance(current, PlatformVariantRevision) else None
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
                    or (expected_platforms == ["telegram"] and candidate_payload.get("platform") == "telegram")
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
