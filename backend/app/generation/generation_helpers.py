from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select

from app.automations.telegram.handlers import sha256_canonical
from app.core.redaction import redact_secrets, redact_string
from app.generation.default_prompts import prompt_checksum
from app.generation.models import (
    ContentPack,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.multiplatform import (
    PLATFORM_PROMPT_PURPOSE,
    payload_claims,
)
from app.generation.platform_limits import (
    BLOG_BODY_MIN,
    BLOG_EXCERPT_MAX,
    BLOG_SEO_DESCRIPTION_MAX,
    BLOG_SLUG_MAX,
    BLOG_TAG_MAX,
    BLOG_TITLE_MAX,
    INSTAGRAM_CAPTION_MAX,
    INSTAGRAM_CAROUSEL_MAX,
    INSTAGRAM_CTA_MAX,
    INSTAGRAM_HASHTAG_MAX,
    INSTAGRAM_HOOK_MAX,
    MEDIA_ALT_TEXT_MAX,
    X_MEDIA_PER_POST_MAX,
    X_POST_WEIGHT_MAX,
    X_POSTS_MAX,
)
from app.generation.platform_media import (
    trusted_story_media as _trusted_story_media,
)
from app.generation.platform_media import (
    validate_payload_media_assignments,
)
from app.generation.platform_schemas import (
    Platform,
    TelegramVariantPayload,
)
from app.generation.platform_validation import (
    revision_gates_from_issues,
    validate_platform_payload,
)
from app.generation.providers.base import ProviderMessage
from app.generation.revision_fence import (
    RegenerationFenceConflict,
    RegenerationFenceOwner,
    acquire_regeneration_fence,
)
from app.generation.telegram_schema import assemble_telegram_variant
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, job_payload_copy
from app.research.citations import CitationIntegrityError, validate_citations
from app.research.schemas import CitationRef, Claim
from app.stories.evidence import EvidenceRecord
from app.stories.models import StoryEvidenceSnapshot


def platform_limits_for(platform: Platform) -> dict[str, int]:
    if platform == "instagram":
        return {
            "caption_max": INSTAGRAM_CAPTION_MAX,
            "hashtag_max": INSTAGRAM_HASHTAG_MAX,
            "carousel_max": INSTAGRAM_CAROUSEL_MAX,
            "hook_max": INSTAGRAM_HOOK_MAX,
            "cta_max": INSTAGRAM_CTA_MAX,
            "alt_text_max": MEDIA_ALT_TEXT_MAX,
        }
    if platform == "x":
        return {
            "post_weight_max": X_POST_WEIGHT_MAX,
            "posts_max": X_POSTS_MAX,
            "media_per_post_max": X_MEDIA_PER_POST_MAX,
            "url_weight": 23,
            "alt_text_max": MEDIA_ALT_TEXT_MAX,
        }
    if platform == "blog":
        return {
            "title_max": BLOG_TITLE_MAX,
            "slug_max": BLOG_SLUG_MAX,
            "excerpt_max": BLOG_EXCERPT_MAX,
            "body_min": BLOG_BODY_MIN,
            "tag_max": BLOG_TAG_MAX,
            "seo_description_max": BLOG_SEO_DESCRIPTION_MAX,
            "alt_text_max": MEDIA_ALT_TEXT_MAX,
        }
    return {"body_max": 4096, "button_max": 8}


def _platform_stage_input(
    *,
    platform: Platform,
    canonical_story: dict[str, Any],
    brand_profile: dict[str, Any],
    prompt_checksum: str,
    provider_profile_id: UUID,
    instruction: str | None,
    source_media: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    limits = platform_limits_for(platform)
    preferences = dict(brand_profile.get("platform_preferences") or {}).get(platform, {})
    direction = (preferences.get("direction") if isinstance(preferences, dict) else None) or (
        "rtl" if brand_profile.get("output_language") == "fa" else "ltr"
    )
    input_payload = {
        "canonical_story_json": json.dumps(canonical_story, ensure_ascii=False, sort_keys=True),
        "brand_profile_json": json.dumps(brand_profile, ensure_ascii=False, sort_keys=True),
        "platform_limits_json": json.dumps(limits, sort_keys=True),
        "source_media_json": json.dumps(source_media, ensure_ascii=False, sort_keys=True),
        "direction": direction,
        "instruction": instruction or "",
    }
    input_hash = sha256_canonical(
        {
            "story_revision": canonical_story,
            "brand": brand_profile,
            "prompt_checksum": prompt_checksum,
            "provider_profile_id": str(provider_profile_id),
            "platform": platform,
            "platform_limits": limits,
            "source_media": source_media,
            "instruction": instruction,
        }
    )
    return input_payload, input_hash


def _pack_job_result(
    pack_id: UUID,
    platforms: list[Platform],
    revisions: list[dict[str, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content_pack_id": str(pack_id),
        "platforms": list(platforms),
        "revisions": [dict(item) for item in revisions],
    }
    if len(revisions) == 1:
        result.update(revisions[0])
    return result


async def _require_exact_active_prompt(
    session: Any,
    platform: Platform,
    prompt_id: UUID,
    prompt_checksum: str,
) -> PromptTemplateVersion:
    active = list(
        await session.scalars(
            select(PromptTemplateVersion)
            .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.prompt_template_id)
            .where(
                PromptTemplateVersion.is_active.is_(True),
                PromptTemplate.purpose_key == PLATFORM_PROMPT_PURPOSE[platform],
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if len(active) != 1 or active[0].id != prompt_id or active[0].checksum_sha256 != prompt_checksum:
        raise PermanentJobError(
            code="generation_platform_prompt_configuration_invalid",
            message="Platform prompt configuration is invalid",
        )
    try:
        require_prompt_integrity(active[0])
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_integrity_failed",
            message="Generation prompt snapshot integrity failed",
        ) from None
    return active[0]


async def _require_exact_active_canonical_prompt(
    session: Any,
    prompt_id: UUID,
    prompt_checksum: str,
) -> PromptTemplateVersion:
    active = list(
        await session.scalars(
            select(PromptTemplateVersion)
            .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.prompt_template_id)
            .where(
                PromptTemplateVersion.is_active.is_(True),
                PromptTemplate.purpose_key == "canonical_story",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if len(active) != 1 or active[0].id != prompt_id or active[0].checksum_sha256 != prompt_checksum:
        raise PermanentJobError(
            code="generation_canonical_prompt_configuration_invalid",
            message="Canonical prompt configuration is invalid",
        )
    try:
        require_prompt_integrity(active[0])
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_integrity_failed",
            message="Generation prompt snapshot integrity failed",
        ) from None
    return active[0]


async def _require_exact_regeneration_dispatch(
    session: Any,
    *,
    platform: Platform,
    variant_id: UUID,
    base_revision_id: UUID,
    base_content_hash: str,
    prompt_id: UUID,
    prompt_checksum: str,
    workflow_job_id: UUID,
    workflow_attempt: int,
    lease_owner: str | None,
) -> RegenerationFenceOwner:
    # Global order for this dispatch boundary:
    # variant -> prompt -> revision -> workflow job fence.
    variant = await session.scalar(
        select(PlatformVariant)
        .where(PlatformVariant.id == variant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if variant is None or variant.platform != platform:
        raise NeedsReviewJobError(
            code="generation_regeneration_base_stale",
            message="Regeneration base revision is no longer current",
        )
    await _require_exact_active_prompt(
        session,
        platform,
        prompt_id,
        prompt_checksum,
    )
    current = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.platform_variant_id == variant.id)
        .order_by(
            PlatformVariantRevision.revision_number.desc(),
            PlatformVariantRevision.created_at.desc(),
            PlatformVariantRevision.id.desc(),
        )
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None or current.id != base_revision_id or current.content_hash != base_content_hash:
        raise NeedsReviewJobError(
            code="generation_regeneration_base_stale",
            message="Regeneration base revision is no longer current",
        )
    if not isinstance(lease_owner, str) or not lease_owner.strip():
        raise RetryableJobError(
            code="generation_regeneration_fence_unavailable",
            message="Regeneration worker lease is unavailable",
        )
    try:
        return await acquire_regeneration_fence(
            session,
            variant_id=variant_id,
            base_revision_id=base_revision_id,
            base_content_hash=base_content_hash,
            workflow_job_id=workflow_job_id,
            workflow_attempt=workflow_attempt,
            lease_owner=lease_owner,
        )
    except RegenerationFenceConflict:
        raise RetryableJobError(
            code="generation_regeneration_fence_unavailable",
            message="Regeneration variant is reserved by another live worker",
        ) from None


def _checkpoint_ids(artifact: dict[str, Any]) -> tuple[UUID, UUID, UUID]:
    try:
        return (
            UUID(str(artifact["content_pack_id"])),
            UUID(str(artifact["variant_id"])),
            UUID(str(artifact["revision_id"])),
        )
    except KeyError, TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint is invalid",
        ) from None


async def _checkpoint_rows(
    session: Any,
    *,
    pack_id: UUID,
    variant_id: UUID,
    revision_id: UUID,
) -> tuple[ContentPack | None, PlatformVariant | None, PlatformVariantRevision | None]:
    pack = await session.scalar(
        select(ContentPack).where(ContentPack.id == pack_id).execution_options(populate_existing=True)
    )
    variant = await session.scalar(
        select(PlatformVariant)
        .where(PlatformVariant.id == variant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    revision = await session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.id == revision_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return pack, variant, revision


async def _checkpoint_parent(
    session: Any,
    revision: PlatformVariantRevision | None,
    *,
    expected_platform: Platform,
    expected_regeneration_base: tuple[UUID, str] | None,
) -> PlatformVariantRevision | None:
    if revision is None or (expected_platform != "telegram" and expected_regeneration_base is None):
        return None
    parent = None
    if revision.parent_revision_id is not None:
        parent = await session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.id == revision.parent_revision_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if parent is None or parent.platform_variant_id != revision.platform_variant_id:
            raise NeedsReviewJobError(
                code="generation_checkpoint_invalid",
                message="Generation checkpoint parent linkage is invalid",
            )
    if expected_regeneration_base is not None:
        expected_parent_id, expected_parent_hash = expected_regeneration_base
        if (
            revision.parent_revision_id != expected_parent_id
            or parent is None
            or parent.content_hash != expected_parent_hash
        ):
            raise NeedsReviewJobError(
                code="generation_checkpoint_invalid",
                message="Generation checkpoint regeneration base is invalid",
            )
    return parent


def _telegram_checkpoint_expectations(
    authored: Any,
    *,
    parent: PlatformVariantRevision | None,
    default_direction: Literal["ltr", "rtl"] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        assert default_direction is not None
        content = assemble_telegram_variant(
            authored,
            trusted_parent=parent.content if parent is not None else None,
            default_direction=default_direction,
        ).model_dump(mode="json")
        payload = TelegramVariantPayload.model_validate(content)
        return content, revision_gates_from_issues(validate_platform_payload("telegram", payload))
    except TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint Telegram context is invalid",
        ) from None


def _require_checkpoint_linkage(
    artifact: dict[str, Any],
    *,
    ids: tuple[UUID, UUID, UUID],
    pack: ContentPack | None,
    variant: PlatformVariant | None,
    revision: PlatformVariantRevision | None,
    expected_platform: Platform,
    expected_story_revision_id: UUID,
    expected_brand_profile_id: UUID,
    expected_attempt_id: UUID,
    expected_content: dict[str, Any] | None,
    expected_evidence_map: list[dict[str, Any]],
    expected_validation_results: list[dict[str, Any]] | None,
) -> None:
    pack_id, variant_id, revision_id = ids
    valid = (
        revision is not None
        and variant is not None
        and pack is not None
        and revision.id == revision_id
        and variant.id == variant_id
        and pack.id == pack_id
        and artifact.get("platform") == expected_platform
        and variant.platform == expected_platform
        and revision.platform_variant_id == variant.id
        and variant.content_pack_id == pack.id
        and pack.story_revision_id == expected_story_revision_id
        and pack.brand_profile_id == expected_brand_profile_id
        and revision.generation_attempt_id == expected_attempt_id
        and revision.content == expected_content
        and revision.evidence_map == expected_evidence_map
        and revision.validation_results == expected_validation_results
        and revision.content_hash
        == sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map})
    )
    if not valid:
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint linkage is invalid",
        )


def _checkpoint_gates(revision: PlatformVariantRevision) -> list[dict[str, Any]]:
    gates = revision.validation_results
    valid = (
        isinstance(gates, list)
        and bool(gates)
        and all(
            isinstance(gate, dict) and isinstance(gate.get("gate"), str) and isinstance(gate.get("ok"), bool)
            for gate in gates
        )
    )
    if not valid:
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint validation results are invalid",
        )
    return gates


def _require_checkpoint_citations(
    *,
    platform: Platform,
    authored: Any,
    expected_evidence_map: list[dict[str, Any]],
    evidence: dict[UUID, EvidenceRecord],
) -> None:
    try:
        claims = (
            [
                Claim(
                    text="Telegram package",
                    citations=[CitationRef.model_validate(item) for item in expected_evidence_map],
                )
            ]
            if platform == "telegram"
            else payload_claims(platform, authored)
        )
        validate_citations(claims, evidence)
    except TypeError, ValueError:
        raise NeedsReviewJobError(
            code="citation_integrity",
            message="Generation checkpoint citations failed integrity validation",
        ) from None


async def _require_checkpoint_media(
    session: Any,
    *,
    platform: Platform,
    authored: Any,
    evidence: dict[UUID, EvidenceRecord],
    trusted_media_loader: Any,
) -> None:
    if platform == "telegram":
        return
    authorized_media, _source_media = await trusted_media_loader(
        session,
        evidence,
        lock_rows=True,
    )
    try:
        validate_payload_media_assignments(authored, authorized_media)
    except CitationIntegrityError:
        raise NeedsReviewJobError(
            code="media_integrity",
            message="Generation checkpoint media failed integrity validation",
        ) from None


async def _artifact_requires_review(
    session: Any,
    artifact: dict[str, Any],
    *,
    expected_platform: Platform,
    expected_story_revision_id: UUID,
    expected_brand_profile_id: UUID,
    expected_attempt_id: UUID,
    authored: Any,
    expected_content: dict[str, Any] | None,
    expected_evidence_map: list[dict[str, Any]],
    expected_validation_results: list[dict[str, Any]] | None,
    evidence: dict[UUID, EvidenceRecord],
    telegram_default_direction: Literal["ltr", "rtl"] | None = None,
    expected_regeneration_base: tuple[UUID, str] | None = None,
    trusted_media_loader: Any = _trusted_story_media,
) -> bool:
    ids = _checkpoint_ids(artifact)
    pack, variant, revision = await _checkpoint_rows(
        session,
        pack_id=ids[0],
        variant_id=ids[1],
        revision_id=ids[2],
    )
    locked_parent = await _checkpoint_parent(
        session,
        revision,
        expected_platform=expected_platform,
        expected_regeneration_base=expected_regeneration_base,
    )
    if revision is not None and expected_platform == "telegram":
        expected_content, expected_validation_results = _telegram_checkpoint_expectations(
            authored,
            parent=locked_parent,
            default_direction=telegram_default_direction,
        )
    _require_checkpoint_linkage(
        artifact,
        ids=ids,
        pack=pack,
        variant=variant,
        revision=revision,
        expected_platform=expected_platform,
        expected_story_revision_id=expected_story_revision_id,
        expected_brand_profile_id=expected_brand_profile_id,
        expected_attempt_id=expected_attempt_id,
        expected_content=expected_content,
        expected_evidence_map=expected_evidence_map,
        expected_validation_results=expected_validation_results,
    )
    assert revision is not None
    gates = _checkpoint_gates(revision)
    _require_checkpoint_citations(
        platform=expected_platform,
        authored=authored,
        expected_evidence_map=expected_evidence_map,
        evidence=evidence,
    )
    await _require_checkpoint_media(
        session,
        platform=expected_platform,
        authored=authored,
        evidence=evidence,
        trusted_media_loader=trusted_media_loader,
    )
    return any(not gate["ok"] for gate in gates)


def _prompt_snapshot(
    prompt: PromptTemplateVersion,
    messages: tuple[ProviderMessage, ProviderMessage] | None = None,
) -> dict[str, Any]:
    value = {
        "prompt_template_version_id": str(prompt.id),
        "version": prompt.version,
        "system_template": prompt.system_template,
        "user_template": prompt.user_template,
        "output_schema_version": prompt.output_schema_version,
        "output_schema": prompt.output_schema,
        "checksum_sha256": prompt.checksum_sha256,
    }
    if messages is not None:
        value["executed_messages"] = [{"role": item.role, "content": item.content} for item in messages]
    return value


def require_prompt_integrity(prompt: PromptTemplateVersion) -> None:
    checksum = prompt_checksum(
        prompt.system_template,
        prompt.user_template,
        dict(prompt.output_schema or {}),
    )
    if checksum != prompt.checksum_sha256:
        raise ValueError("generation prompt snapshot checksum is invalid")


def stage_input_hash(value: object) -> str:
    return sha256_canonical(value)


def _safe_error_code(value: object, fallback: str) -> str:
    raw = str(value).strip().lower()
    if redact_string(raw) != raw:
        return fallback
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", raw).strip("_.-")
    return normalized[:120] or fallback


def _redacted_dict(value: object) -> dict[str, Any]:
    redacted = redact_secrets(value)
    return redacted if isinstance(redacted, dict) else {}


def _redacted_list(value: object) -> list[Any]:
    redacted = redact_secrets(value)
    return redacted if isinstance(redacted, list) else []


def _required_uuid(payload: dict[str, Any], key: str) -> UUID:
    try:
        return UUID(str(payload[key]))
    except KeyError, TypeError, ValueError:
        raise PermanentJobError(
            code="generation_job_payload_invalid",
            message="Generation job payload is invalid",
        ) from None


def _job_payload(job: JobExecution | object) -> dict[str, Any]:
    try:
        return job_payload_copy(cast(Any, job))
    except TypeError:
        raise PermanentJobError(
            code="generation_job_payload_invalid",
            message="Generation job payload is invalid",
        ) from None


def _pack_budget_state(job: JobExecution | object, payload: dict[str, Any]) -> tuple[datetime, Decimal]:
    raw_started = payload.get("generation_budget_started_at")
    raw_cost = payload.get("generation_budget_cost_usd", "0")
    try:
        started = (
            datetime.fromisoformat(raw_started) if isinstance(raw_started, str) else getattr(job, "created_at", None)
        )
        if started is None and not isinstance(job, JobExecution):
            # Direct unit-handler doubles predate the immutable execution snapshot.
            started = datetime.now(UTC)
        if not isinstance(started, datetime):
            raise ValueError
        if started.tzinfo is None or started.utcoffset() is None:
            raise ValueError
        cost = Decimal(str(raw_cost))
        if not cost.is_finite() or cost < 0:
            raise ValueError
    except AttributeError, InvalidOperation, TypeError, ValueError:
        raise PermanentJobError(
            code="generation_pack_budget_invalid",
            message="Generation pack budget state is invalid",
        ) from None
    return started.astimezone(UTC), cost


async def _checkpoint_execution(
    job: JobExecution | object,
    context: JobContext,
    *,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> JobExecution | object:
    if isinstance(job, JobExecution):
        await JobRepository(context.session).checkpoint_job(
            job_id=job.id,
            worker_id=job.lease_owner,
            payload=payload,
            result=result,
        )
        return job.with_payload(payload) if payload is not None else job
    # Direct handler unit tests use lightweight doubles. Production handlers
    # receive JobExecution exclusively through JobHandlerRegistry.
    legacy_job: Any = job
    if payload is not None:
        legacy_job.payload = payload
    if result is not None:
        legacy_job.result = result
    return job


def render_prompt_messages(
    prompt: PromptTemplateVersion | Any,
    values: dict[str, Any],
) -> tuple[ProviderMessage, ProviderMessage]:
    try:
        rendered = prompt.user_template.format(**values)
    except KeyError, ValueError:
        raise ValueError("generation prompt template cannot be rendered") from None
    return (
        ProviderMessage(role="system", content=prompt.system_template),
        ProviderMessage(role="user", content=rendered),
    )


def _evidence_record(row: StoryEvidenceSnapshot) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_key=row.evidence_key,
        evidence_snapshot_id=row.id,
        content_item_id=row.content_item_id,
        title=row.title,
        content_text=row.content_text,
        content_sha256=row.content_sha256,
        source_url=row.source_url,
        authors=tuple(row.authors or []),
        published_at=row.published_at,
        captured_at=row.captured_at,
    )
