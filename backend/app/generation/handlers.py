from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python
from sqlalchemy import func, select

from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_secrets, redact_string
from app.generation.canonical import CanonicalStoryOutput, validate_canonical_output
from app.generation.default_prompts import manual_generation_provider_schema, prompt_checksum
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.multiplatform import (
    MANUAL_PLATFORM_ADAPTERS,
    PLATFORM_ORDER,
    PLATFORM_PROMPT_PURPOSE,
    deduplicate_preserving_order,
    ordered_distinct_citations,
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
    BlogVariantPayload,
    InstagramSlide,
    InstagramVariantPayload,
    MediaAssignment,
    Platform,
    TelegramVariantPayload,
    XPost,
    XVariantPayload,
)
from app.generation.platform_validation import (
    ValidationIssue,
    revision_gates_from_issues,
    validate_platform_payload,
)
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.revision_fence import (
    RegenerationFenceConflict,
    RegenerationFenceOwner,
    acquire_regeneration_fence,
    clear_regeneration_fence,
    require_revision_write_allowed,
)
from app.generation.telegram_schema import TelegramRewriteOutput, assemble_telegram_variant
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, job_payload_copy
from app.research.citations import CitationIntegrityError, validate_citations
from app.research.models import ResearchRun
from app.research.schemas import CitationRef, Claim
from app.stories.evidence import EvidenceRecord
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


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
) -> bool:
    try:
        pack_id = UUID(str(artifact["content_pack_id"]))
        variant_id = UUID(str(artifact["variant_id"]))
        revision_id = UUID(str(artifact["revision_id"]))
    except KeyError, TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint is invalid",
        ) from None
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
    locked_parent = None
    if revision is not None and (expected_platform == "telegram" or expected_regeneration_base is not None):
        if revision.parent_revision_id is not None:
            locked_parent = await session.scalar(
                select(PlatformVariantRevision)
                .where(PlatformVariantRevision.id == revision.parent_revision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked_parent is None or locked_parent.platform_variant_id != revision.platform_variant_id:
                raise NeedsReviewJobError(
                    code="generation_checkpoint_invalid",
                    message="Generation checkpoint parent linkage is invalid",
                )
        if expected_regeneration_base is not None:
            expected_parent_id, expected_parent_hash = expected_regeneration_base
            if (
                revision.parent_revision_id != expected_parent_id
                or locked_parent is None
                or locked_parent.content_hash != expected_parent_hash
            ):
                raise NeedsReviewJobError(
                    code="generation_checkpoint_invalid",
                    message="Generation checkpoint regeneration base is invalid",
                )
    if revision is not None and expected_platform == "telegram":
        try:
            assert telegram_default_direction is not None
            expected_content = assemble_telegram_variant(
                authored,
                trusted_parent=locked_parent.content if locked_parent is not None else None,
                default_direction=telegram_default_direction,
            ).model_dump(mode="json")
            telegram_payload = TelegramVariantPayload.model_validate(expected_content)
            expected_validation_results = revision_gates_from_issues(
                validate_platform_payload("telegram", telegram_payload)
            )
        except TypeError, ValueError:
            raise NeedsReviewJobError(
                code="generation_checkpoint_invalid",
                message="Generation checkpoint Telegram context is invalid",
            ) from None
    if (
        revision is None
        or variant is None
        or pack is None
        or revision.id != revision_id
        or variant.id != variant_id
        or pack.id != pack_id
        or artifact.get("platform") != expected_platform
        or variant.platform != expected_platform
        or revision.platform_variant_id != variant.id
        or variant.content_pack_id != pack.id
        or pack.story_revision_id != expected_story_revision_id
        or pack.brand_profile_id != expected_brand_profile_id
        or revision.generation_attempt_id != expected_attempt_id
        or revision.content != expected_content
        or revision.evidence_map != expected_evidence_map
        or revision.validation_results != expected_validation_results
        or revision.content_hash
        != sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map})
    ):
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint linkage is invalid",
        )
    gates = revision.validation_results
    if (
        not isinstance(gates, list)
        or not gates
        or any(
            not isinstance(gate, dict) or not isinstance(gate.get("gate"), str) or not isinstance(gate.get("ok"), bool)
            for gate in gates
        )
    ):
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint validation results are invalid",
        )
    try:
        if expected_platform == "telegram":
            citations = [CitationRef.model_validate(item) for item in expected_evidence_map]
            validate_citations([Claim(text="Telegram package", citations=citations)], evidence)
        else:
            validate_citations(payload_claims(expected_platform, authored), evidence)
    except TypeError, ValueError:
        raise NeedsReviewJobError(
            code="citation_integrity",
            message="Generation checkpoint citations failed integrity validation",
        ) from None
    if expected_platform != "telegram":
        authorized_media, _source_media = await _trusted_story_media(
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
        return job_payload_copy(job)
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


async def _invoke(
    context: JobContext,
    *,
    profile_resolver: Any,
    profile_id: UUID,
    prompt: PromptTemplateVersion,
    purpose: str,
    story_revision_id: UUID | None,
    input_payload: dict[str, Any],
    input_hash: str,
    workflow_job_id: UUID,
    workflow_attempt: int,
    validate_output: Callable[[dict[str, Any]], Any],
    expected_provider_configuration_revision: str | None = None,
    expected_provider_configuration_checksum: str | None = None,
    pack_budget_started_at: datetime | None = None,
    prior_pack_cost_usd: Decimal = Decimal("0"),
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
    fault_injector: FaultInjector | None = None,
) -> tuple[GenerationRun, GenerationAttempt, Any]:
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()
    profile = await context.session.get(AIProviderProfile, profile_id)
    if profile is None:
        raise PermanentJobError(
            code="generation_profile_missing",
            message="Generation provider profile was not found",
        )
    try:
        resolved = await profile_resolver.resolve(profile, None)
    except Exception:
        raise PermanentJobError(
            code="generation_profile_unavailable",
            message="Generation provider profile is unavailable",
        ) from None
    try:
        require_prompt_integrity(prompt)
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_integrity_failed",
            message="Generation prompt snapshot integrity failed",
        ) from None
    input_hash = sha256_canonical(
        {
            "workflow_job_id": str(workflow_job_id),
            "stage_input_hash": input_hash,
            "resolved_model": resolved.model,
            "purpose": purpose,
        }
    )
    stage_key = f"{workflow_job_id}:{purpose}:{input_hash}"
    bind = context.session.get_bind()
    if bind.dialect.name == "postgresql":
        lock_id = int.from_bytes(
            __import__("hashlib").sha256(stage_key.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await context.session.execute(select(func.pg_advisory_xact_lock(lock_id)))
    existing = await context.session.scalar(
        select(GenerationRun)
        .where(
            GenerationRun.provider_profile_id == profile.id,
            GenerationRun.prompt_template_version_id == prompt.id,
            GenerationRun.input_hash == input_hash,
        )
        .with_for_update()
    )
    if existing is not None and existing.status == "succeeded" and existing.output_payload:
        completed = await context.session.scalar(
            select(GenerationAttempt)
            .where(
                GenerationAttempt.generation_run_id == existing.id,
                GenerationAttempt.status == "succeeded",
            )
            .order_by(GenerationAttempt.attempt_number.desc())
        )
        if completed is None:
            raise RetryableJobError(
                code="generation_attempt_missing",
                message="Durable generation attempt is missing",
            )
        durable_output = {key: value for key, value in dict(existing.output_payload).items() if key != "_artifact"}
        try:
            validated = validate_output(durable_output)
        except CitationIntegrityError:
            raise NeedsReviewJobError(
                code="citation_integrity",
                message="Generation citations failed integrity validation",
            ) from None
        except ValidationError, ValueError:
            raise NeedsReviewJobError(
                code="generation_output_invalid",
                message="Generation output failed validation",
            ) from None
        return existing, completed, validated
    now = datetime.now(UTC)
    try:
        messages = render_prompt_messages(prompt, input_payload)
    except ValueError:
        raise PermanentJobError(
            code="generation_prompt_render_invalid",
            message="Generation prompt cannot be rendered",
        ) from None
    if existing is None:
        run = GenerationRun(
            id=uuid4(),
            story_revision_id=story_revision_id,
            provider_profile_id=profile.id,
            prompt_template_version_id=prompt.id,
            requested_model=redact_string(resolved.model),
            status="running",
            input_hash=input_hash,
            request_payload={},
            output_payload={},
            started_at=now,
        )
        context.session.add(run)
        attempts: list[GenerationAttempt] = []
        await context.session.flush()
    else:
        run = existing
        if run.requested_model is not None:
            run.requested_model = redact_string(run.requested_model)
        execution = (run.request_payload or {}).get("execution") or {}
        if run.status == "running" and execution.get("workflow_attempt") == workflow_attempt:
            raise RetryableJobError(
                code="generation_stage_in_progress",
                message="Generation stage is already running",
            )
        attempts = list(
            await context.session.scalars(
                select(GenerationAttempt).where(GenerationAttempt.generation_run_id == run.id)
            )
        )
        for stale in attempts:
            if stale.status == "running":
                stale.status = "failed"
                stale.error_class = "retryable"
                stale.error_code = "generation_attempt_interrupted"
                stale.error_message = "Prior generation attempt was interrupted"
                stale.finished_at = now
        run.status = "running"
        run.error_class = run.error_code = run.error_message = None
        run.finished_at = None
    attempt = GenerationAttempt(
        id=uuid4(),
        generation_run_id=run.id,
        attempt_number=max((item.attempt_number for item in attempts), default=0) + 1,
        provider=resolved.provider_type,
        requested_model=redact_string(resolved.model),
        resolved_model=redact_string(resolved.model),
        prompt_snapshot=_redacted_dict(_prompt_snapshot(prompt, messages)),
        response_payload={},
        usage={},
        validation_errors=[],
        status="running",
        started_at=now,
    )
    context.session.add(attempt)
    run.request_payload = _redacted_dict(
        {
            "stage_key": stage_key,
            "input": input_payload,
            "prompt": _prompt_snapshot(prompt, messages),
            "execution": {
                "workflow_job_id": str(workflow_job_id),
                "workflow_attempt": workflow_attempt,
                "active_attempt_id": str(attempt.id),
            },
        }
    )
    await context.session.flush()
    await context.session.commit()

    request = GenerationProviderRequest(
        run_id=run.id,
        purpose=purpose,
        requested_model=resolved.model,
        messages=messages,
        response_schema=dict(prompt.output_schema or {}),
        metadata={
            "provider_profile_id": str(profile.id),
            "prompt_template_version_id": str(prompt.id),
            "input_payload": dict(input_payload),
            "max_output_tokens": getattr(resolved, "max_output_tokens", None),
        },
    )
    provider_completed = False
    try:
        if before_provider_call is not None:
            await before_provider_call()
            # The callback may use SELECT ... FOR UPDATE. Release that read
            # transaction before crossing the provider/network boundary.
            await context.session.commit()
        if expected_provider_configuration_revision is not None or expected_provider_configuration_checksum is not None:
            await context.session.refresh(profile)
            try:
                latest = await profile_resolver.resolve(profile, None)
            except Exception:
                old_client = getattr(resolved.provider, "http_client", None)
                if old_client is not None and hasattr(old_client, "aclose"):
                    await old_client.aclose()
                raise PermanentJobError(
                    code="generation_provider_configuration_changed",
                    message="Generation provider configuration changed after enqueue",
                ) from None
            if (
                expected_provider_configuration_revision is not None
                and latest.configuration_revision != expected_provider_configuration_revision
            ) or (
                expected_provider_configuration_checksum is not None
                and latest.configuration_checksum != expected_provider_configuration_checksum
            ):
                latest_client = getattr(latest.provider, "http_client", None)
                if latest_client is not None and hasattr(latest_client, "aclose"):
                    await latest_client.aclose()
                old_client = getattr(resolved.provider, "http_client", None)
                if old_client is not None and hasattr(old_client, "aclose"):
                    await old_client.aclose()
                raise PermanentJobError(
                    code="generation_provider_configuration_changed",
                    message="Generation provider configuration changed after enqueue",
                )
            old_client = getattr(resolved.provider, "http_client", None)
            if old_client is not None and old_client is not getattr(latest.provider, "http_client", None):
                await old_client.aclose()
            resolved = latest
        max_attempts = getattr(resolved, "max_attempts", None)
        if max_attempts is not None and attempt.attempt_number > max_attempts:
            raise NeedsReviewJobError(
                code="generation_provider_attempt_budget_exhausted",
                message="Generation provider attempt budget is exhausted",
            )
        remaining_seconds: float | None = None
        max_elapsed_seconds = getattr(resolved, "max_elapsed_seconds", None)
        if max_elapsed_seconds is not None and pack_budget_started_at is not None:
            remaining_seconds = max_elapsed_seconds - (datetime.now(UTC) - pack_budget_started_at).total_seconds()
            if remaining_seconds <= 0:
                raise NeedsReviewJobError(
                    code="generation_pack_elapsed_budget_exhausted",
                    message="Generation pack elapsed-time budget is exhausted",
                )
        if remaining_seconds is None:
            result = await resolved.provider.generate(request)
        else:
            try:
                async with asyncio.timeout(remaining_seconds):
                    result = await resolved.provider.generate(request)
            except TimeoutError:
                raise NeedsReviewJobError(
                    code="generation_pack_elapsed_budget_exhausted",
                    message="Generation pack elapsed-time budget is exhausted",
                ) from None
        provider_completed = True
        normalized_usage, call_cost = _usage_with_qualified_pricing(result.usage, resolved)
        result = replace(result, usage=normalized_usage)
        max_pack_cost_usd = getattr(resolved, "max_pack_cost_usd", None)
        if max_pack_cost_usd is not None and prior_pack_cost_usd + call_cost > max_pack_cost_usd:
            raise NeedsReviewJobError(
                code="generation_pack_cost_budget_exhausted",
                message="Generation pack cost budget is exhausted",
            )
        await injector.hit(
            "generation.after_provider_before_persist",
            {
                "workflow_job_id": str(workflow_job_id),
                "generation_run_id": str(run.id),
                "generation_attempt_id": str(attempt.id),
                "purpose": purpose,
            },
        )
        validated = validate_output(result.output)
    except Exception as exc:
        await context.session.rollback()
        error_class = getattr(exc, "classification", getattr(exc, "error_class", None))
        provider_code = _safe_error_code(getattr(exc, "code", ""), "generation_provider_failed")
        mapped: RetryableJobError | NeedsReviewJobError | PermanentJobError
        if isinstance(exc, PermanentJobError):
            mapped = exc
            error_class = "permanent"
        elif isinstance(exc, NeedsReviewJobError):
            mapped = exc
            error_class = "needs_review"
        elif isinstance(exc, RetryableJobError):
            mapped = exc
            error_class = "retryable"
        elif provider_completed and isinstance(exc, CitationIntegrityError):
            mapped = NeedsReviewJobError(
                code="citation_integrity",
                message="Generation citations failed integrity validation",
            )
            error_class = "needs_review"
        elif provider_completed and isinstance(exc, (ValidationError, ValueError)):
            mapped = NeedsReviewJobError(
                code="generation_output_invalid",
                message="Generation output failed validation",
            )
            error_class = "needs_review"
        elif error_class == "permanent":
            mapped = PermanentJobError(
                code=provider_code,
                message="Generation provider rejected the request",
            )
        elif error_class == "needs_review":
            mapped = NeedsReviewJobError(
                code=provider_code,
                message="Generation requires operator review",
            )
        elif isinstance(exc, ValueError):
            mapped = PermanentJobError(
                code="generation_provider_contract_invalid",
                message="Generation provider contract is invalid",
            )
            error_class = "permanent"
        else:
            retry_after_seconds = getattr(exc, "retry_after_seconds", None)
            if retry_after_seconds is None:
                base_delay = min(120, 5 * (2 ** max(0, workflow_attempt - 1)))
                jitter_seed = int.from_bytes(workflow_job_id.bytes[-2:], byteorder="big") / 65_535
                retry_after_seconds = base_delay + (base_delay * 0.2 * jitter_seed)
            mapped = RetryableJobError(
                code=provider_code,
                message="Generation provider call failed",
                retry_at=datetime.now(UTC) + timedelta(seconds=retry_after_seconds),
            )
            error_class = "retryable"
        async with context.session.begin():
            current_run = await context.session.scalar(
                select(GenerationRun)
                .where(GenerationRun.id == run.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            current_attempt = await context.session.scalar(
                select(GenerationAttempt)
                .where(GenerationAttempt.id == attempt.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if current_run is not None and current_attempt is not None:
                active = ((current_run.request_payload or {}).get("execution") or {}).get("active_attempt_id")
                if active == str(attempt.id):
                    durable_error_code = redact_string(mapped.code)
                    durable_error_message = redact_string(mapped.message)
                    current_attempt.status = "failed"
                    if provider_completed:
                        current_attempt.usage = _redacted_dict(result.usage)
                    current_attempt.error_class = error_class
                    current_attempt.error_code = durable_error_code
                    current_attempt.error_message = durable_error_message
                    current_attempt.finished_at = datetime.now(UTC)
                    if isinstance(exc, ValidationError):
                        current_attempt.validation_errors = _redacted_list(
                            [
                                {
                                    "type": item["type"],
                                    "loc": [str(part) for part in item["loc"]],
                                    "message": item["msg"],
                                }
                                for item in exc.errors(
                                    include_input=False,
                                    include_url=False,
                                )
                            ]
                        )
                    elif isinstance(getattr(exc, "diagnostic", None), dict):
                        current_attempt.validation_errors = _redacted_list([exc.diagnostic])
                    elif isinstance(exc, CitationIntegrityError):
                        current_attempt.validation_errors = _redacted_list(
                            [
                                {
                                    "code": "citation_integrity",
                                    "message": "Generation citations failed integrity validation",
                                }
                            ]
                        )
                    current_run.status = "failed"
                    current_run.error_class = error_class
                    current_run.error_code = durable_error_code
                    current_run.error_message = durable_error_message
                    current_run.finished_at = datetime.now(UTC)
        raise mapped from None

    async with context.session.begin():
        current_run = await context.session.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current_attempt = await context.session.scalar(
            select(GenerationAttempt)
            .where(GenerationAttempt.id == attempt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current_run is None or current_attempt is None:
            raise RetryableJobError(
                code="generation_stage_missing",
                message="Generation stage disappeared before persistence",
            )
        active = ((current_run.request_payload or {}).get("execution") or {}).get("active_attempt_id")
        if active != str(attempt.id) or current_attempt.status != "running":
            raise RetryableJobError(
                code="generation_stage_superseded",
                message="Generation stage was superseded by another lease",
            )
        durable_output = _redacted_dict(result.output)
        current_attempt.response_payload = durable_output
        current_attempt.resolved_model = redact_string(result.resolved_model)
        current_attempt.usage = _redacted_dict(result.usage)
        current_attempt.status = "succeeded"
        current_attempt.finished_at = datetime.now(UTC)
        current_run.output_payload = durable_output
        current_run.status = "succeeded"
        current_run.finished_at = datetime.now(UTC)
        current_run.error_class = current_run.error_code = current_run.error_message = None
    return current_run, current_attempt, validated


def _usage_with_qualified_pricing(usage: dict[str, Any], resolved: Any) -> tuple[dict[str, Any], Decimal]:
    """Normalize a call cost and use frozen profile pricing when the provider omits it."""

    normalized = dict(usage)
    try:
        supplied = Decimal(str(normalized.get("cost_usd", 0)))
        input_tokens = Decimal(str(normalized.get("input_tokens", 0)))
        output_tokens = Decimal(str(normalized.get("output_tokens", 0)))
    except InvalidOperation, TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_provider_usage_invalid",
            message="Generation provider usage metadata is invalid",
        ) from None
    if (
        not supplied.is_finite()
        or not input_tokens.is_finite()
        or not output_tokens.is_finite()
        or supplied < 0
        or input_tokens < 0
        or output_tokens < 0
    ):
        raise NeedsReviewJobError(
            code="generation_provider_usage_invalid",
            message="Generation provider usage metadata is invalid",
        )
    max_output_tokens = getattr(resolved, "max_output_tokens", None)
    if max_output_tokens is not None and output_tokens > max_output_tokens:
        raise NeedsReviewJobError(
            code="generation_provider_output_budget_exhausted",
            message="Generation provider output-token budget is exhausted",
        )
    priced = Decimal("0")
    if (
        getattr(resolved, "pricing_input_usd_per_million", None) is not None
        and getattr(resolved, "pricing_output_usd_per_million", None) is not None
    ):
        priced = (
            input_tokens * resolved.pricing_input_usd_per_million
            + output_tokens * resolved.pricing_output_usd_per_million
        ) / Decimal(1_000_000)
    effective = max(supplied, priced)
    normalized["cost_usd"] = float(effective)
    normalized["cost_basis"] = "provider_or_profile_max" if priced else "provider"
    return normalized, effective


def build_canonical_generation_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
):
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()

    async def handle(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _job_payload(job)
        budget_started_at, _prior_cost = _pack_budget_state(job, payload)
        story_id = _required_uuid(payload, "story_id")
        prompt_id = _required_uuid(payload, "canonical_prompt_template_version_id")
        profile_id = _required_uuid(payload, "generation_provider_profile_id")
        story = await context.session.scalar(
            select(Story).where(Story.id == story_id, Story.superseded_by_id.is_(None)).with_for_update()
        )
        prompt = await context.session.get(PromptTemplateVersion, prompt_id)
        template = await context.session.get(PromptTemplate, prompt.prompt_template_id) if prompt is not None else None
        if story is None:
            raise PermanentJobError(
                code="generation_story_inactive",
                message="Active generation story was not found",
            )
        if prompt is None:
            raise PermanentJobError(
                code="generation_canonical_prompt_missing", message="Canonical prompt version was not found"
            )
        if template is None or template.purpose_key != "canonical_story":
            raise PermanentJobError(
                code="generation_canonical_prompt_purpose_invalid", message="Canonical prompt purpose is invalid"
            )
        canonical_prompt_checksum = payload.get("canonical_prompt_checksum")
        if not isinstance(canonical_prompt_checksum, str) or canonical_prompt_checksum != prompt.checksum_sha256:
            raise PermanentJobError(
                code="generation_canonical_prompt_configuration_invalid",
                message="Canonical prompt configuration is invalid",
            )
        bound_parent: StoryRevision | None = None
        bound_parent_id = payload.get("research_result_story_revision_id")
        if bound_parent_id is not None:
            try:
                parsed_parent_id = UUID(str(bound_parent_id))
                parsed_run_id = UUID(str(payload["completed_research_run_id"]))
            except KeyError, TypeError, ValueError:
                raise NeedsReviewJobError(
                    code="generation_research_lineage_invalid", message="Bound research revision is invalid"
                ) from None
            bound_parent = await context.session.get(StoryRevision, parsed_parent_id)
            research_run = await context.session.get(ResearchRun, parsed_run_id)
            if (
                bound_parent is None
                or bound_parent.story_id != story_id
                or research_run is None
                or research_run.status != "succeeded"
                or research_run.story_id != story_id
                or research_run.result_story_revision_id != bound_parent.id
            ):
                raise NeedsReviewJobError(
                    code="generation_research_lineage_invalid",
                    message="Bound research revision does not belong to the story",
                )
        snapshot_statement = select(StoryEvidenceSnapshot).where(StoryEvidenceSnapshot.story_id == story_id)
        if bound_parent is not None:
            try:
                bound_snapshot_ids = {
                    UUID(str(item["evidence_snapshot_id"]))
                    for item in bound_parent.citations
                    if item.get("evidence_snapshot_id")
                }
            except AttributeError, TypeError, ValueError:
                raise NeedsReviewJobError(
                    code="generation_research_evidence_invalid", message="Bound research evidence is invalid"
                ) from None
            if not bound_snapshot_ids:
                raise NeedsReviewJobError(
                    code="generation_research_evidence_missing",
                    message="Bound research revision has no evidence",
                )
            snapshot_statement = snapshot_statement.where(StoryEvidenceSnapshot.id.in_(bound_snapshot_ids))
        snapshots = list(
            await context.session.scalars(
                snapshot_statement.order_by(StoryEvidenceSnapshot.captured_at, StoryEvidenceSnapshot.id)
            )
        )
        if not snapshots:
            raise NeedsReviewJobError(
                code="generation_evidence_missing", message="Canonical generation requires evidence"
            )
        if bound_parent is not None and {item.id for item in snapshots} != bound_snapshot_ids:
            raise NeedsReviewJobError(
                code="generation_research_evidence_missing",
                message="Bound research evidence is unavailable",
            )
        evidence = {row.id: _evidence_record(row) for row in snapshots}
        evidence_json = [
            {
                "evidence_snapshot_id": str(row.id),
                "evidence_key": row.evidence_key,
                "source_url": row.source_url,
                "title": row.title,
                "content_text": row.content_text,
                "content_sha256": row.content_sha256,
            }
            for row in snapshots
        ]
        input_hash = sha256_canonical(
            {
                "story_id": str(story_id),
                "evidence": evidence_json,
                "prompt_checksum": prompt.checksum_sha256,
                "provider_profile_id": str(profile_id),
            }
        )

        def validate_canonical(raw: dict[str, Any]) -> CanonicalStoryOutput:
            return validate_canonical_output(CanonicalStoryOutput.model_validate(raw), evidence)

        async def before_provider_call() -> None:
            await _require_exact_active_canonical_prompt(
                context.session,
                prompt_id,
                canonical_prompt_checksum,
            )

        _run, _attempt, output = await _invoke(
            context,
            profile_resolver=profile_resolver,
            profile_id=profile_id,
            prompt=prompt,
            purpose="canonical_story",
            story_revision_id=None,
            input_payload={
                "story_title": story.title,
                "evidence_json": json.dumps(evidence_json, ensure_ascii=False, sort_keys=True),
            },
            input_hash=input_hash,
            workflow_job_id=job.id,
            workflow_attempt=job.attempt_count,
            expected_provider_configuration_revision=payload.get("generation_provider_configuration_revision"),
            expected_provider_configuration_checksum=payload.get("generation_provider_configuration_checksum"),
            pack_budget_started_at=budget_started_at,
            validate_output=validate_canonical,
            before_provider_call=before_provider_call,
            fault_injector=injector,
        )
        locked_story = await context.session.scalar(
            select(Story)
            .where(Story.id == story_id, Story.superseded_by_id.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_story is None:
            raise PermanentJobError(
                code="generation_story_inactive",
                message="Active generation story was not found",
            )
        durable_run = await context.session.scalar(
            select(GenerationRun)
            .where(GenerationRun.id == _run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        artifact = (durable_run.output_payload or {}).get("_artifact") if durable_run else None
        if artifact is not None:
            if not isinstance(artifact, dict) or not {
                "story_revision_id",
                "continuation_job_id",
            }.issubset(artifact):
                raise NeedsReviewJobError(
                    code="generation_checkpoint_invalid",
                    message="Generation checkpoint is invalid",
                )
            return {
                "story_revision_id": artifact["story_revision_id"],
                "continuation_job_id": artifact["continuation_job_id"],
                "idempotent": True,
            }
        if bound_parent is not None:
            parent = bound_parent
        else:
            parent = await context.session.scalar(
                select(StoryRevision)
                .where(StoryRevision.story_id == story_id)
                .order_by(StoryRevision.revision_number.desc())
                .with_for_update()
            )
        revision_number = (
            int(
                await context.session.scalar(
                    select(func.coalesce(func.max(StoryRevision.revision_number), 0)).where(
                        StoryRevision.story_id == story_id
                    )
                )
                or 0
            )
            + 1
        )
        revision = StoryRevision(
            id=uuid4(),
            story_id=story_id,
            parent_revision_id=parent.id if parent else None,
            revision_number=revision_number,
            narrative=output.narrative,
            facts=[item.model_dump(mode="json") for item in output.facts],
            disagreements=[item.model_dump(mode="json") for item in output.disagreements],
            angles=output.angles,
            citations=[
                citation.model_dump(mode="json")
                for claim in [*output.facts, *output.disagreements]
                for citation in claim.citations
            ],
            created_by="generation",
        )
        context.session.add(revision)
        await context.session.flush()
        canonical_cost = Decimal(str((_attempt.usage or {}).get("cost_usd", 0)))
        continuation = payload | {
            "story_revision_id": str(revision.id),
            "generation_budget_started_at": budget_started_at.isoformat(),
            "generation_budget_cost_usd": str(canonical_cost),
        }
        queued = await JobRepository(context.session).enqueue_job(
            job_type="content_pack.generate_telegram",
            payload=continuation,
            idempotency_key=f"content-pack-telegram:{job.id}:{revision.id}",
            origin=JobOrigin.AUTOMATION,
        )
        assert durable_run is not None
        durable_run.output_payload = _redacted_dict(
            {
                **durable_run.output_payload,
                "_artifact": {
                    "story_revision_id": str(revision.id),
                    "continuation_job_id": str(queued.job.id),
                },
            }
        )
        return {"story_revision_id": str(revision.id), "continuation_job_id": str(queued.job.id)}

    return handle


async def _locked_story_evidence(
    context: JobContext,
    story_revision: StoryRevision,
) -> tuple[list[CitationRef], dict[UUID, EvidenceRecord]]:
    try:
        citations = [CitationRef.model_validate(item) for item in story_revision.citations]
    except TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_citations_invalid",
            message="Canonical story citations are invalid",
        ) from None
    if not citations:
        raise NeedsReviewJobError(
            code="generation_citations_missing",
            message="Canonical story citations are missing",
        )
    snapshot_ids = {item.evidence_snapshot_id for item in citations}
    snapshots = list(
        await context.session.scalars(
            select(StoryEvidenceSnapshot).where(
                StoryEvidenceSnapshot.id.in_(snapshot_ids),
                StoryEvidenceSnapshot.story_id == story_revision.story_id,
            )
        )
    )
    records = {row.id: _evidence_record(row) for row in snapshots}
    if set(records) != snapshot_ids:
        raise NeedsReviewJobError(
            code="citation_integrity",
            message="Canonical story evidence is missing",
        )
    try:
        validate_citations([Claim(text="Locked canonical story", citations=citations)], records)
    except CitationIntegrityError:
        raise NeedsReviewJobError(
            code="citation_integrity",
            message="Canonical story citations failed integrity validation",
        ) from None
    return citations, records


def _manual_output_with_ordinary_issues(
    platform: Platform,
    raw: dict[str, Any],
) -> tuple[Any, list[ValidationIssue]]:
    payload_type = MANUAL_PLATFORM_ADAPTERS[platform]
    try:
        payload = payload_type.model_validate(raw)
    except ValidationError:
        schema = manual_generation_provider_schema(payload_type)
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(to_jsonable_python(raw)))
        if errors:
            raise ValueError("manual platform output failed structural validation") from None
        payload = _construct_manual_payload(payload_type, raw)
        # model_construct deliberately skips operational limits. Retain the
        # security-only URL userinfo checks from the strict DTOs.
        if platform == "instagram":
            payload.reject_citation_userinfo()
        elif platform == "x":
            payload.reject_citation_userinfo()
        else:
            payload.reject_url_userinfo()
    return payload, validate_platform_payload(platform, payload)


_LOOSE_MANUAL_MODELS = {
    InstagramVariantPayload,
    InstagramSlide,
    XVariantPayload,
    XPost,
    BlogVariantPayload,
    MediaAssignment,
}


def _construct_manual_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    if origin is list:
        item_type = get_args(annotation)[0]
        return [_construct_manual_value(item_type, item) for item in value]
    if origin in {Union, UnionType}:
        if value is None:
            return None
        target = next(item for item in get_args(annotation) if item is not type(None))
        return _construct_manual_value(target, value)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in _LOOSE_MANUAL_MODELS:
            return _construct_manual_payload(annotation, value)
        return annotation.model_validate(value)
    return TypeAdapter(annotation).validate_python(value)


def _construct_manual_payload(model_type: type[BaseModel], raw: dict[str, Any]) -> BaseModel:
    values = {
        name: _construct_manual_value(model_type.model_fields[name].annotation, value) for name, value in raw.items()
    }
    return model_type.model_construct(**values)


def build_pack_generation_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
):
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()

    async def handle(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _job_payload(job)
        budget_started_at, cumulative_cost = _pack_budget_state(job, payload)
        revision_id = _required_uuid(payload, "story_revision_id")
        brand_id = _required_uuid(payload, "brand_profile_id")
        profile_id = _required_uuid(payload, "generation_provider_profile_id")
        story_revision = await context.session.get(StoryRevision, revision_id)
        brand = await context.session.get(BrandProfile, brand_id)
        if story_revision is None:
            raise PermanentJobError(
                code="generation_story_revision_missing",
                message="Canonical story revision was not found",
            )
        raw_platforms = payload.get("platforms")
        if raw_platforms is None and payload.get("platform") == "telegram":
            raw_platforms = ["telegram"]
        if (
            not isinstance(raw_platforms, list)
            or not raw_platforms
            or any(item not in PLATFORM_PROMPT_PURPOSE for item in raw_platforms)
        ):
            raise PermanentJobError(
                code="generation_job_platforms_invalid",
                message="Generation job platforms are invalid",
            )
        platforms = deduplicate_preserving_order(raw_platforms)
        prompt_ids = payload.get("platform_prompt_template_version_ids")
        if prompt_ids is None and payload.get("platform_prompt_template_version_id"):
            prompt_ids = {"telegram": payload["platform_prompt_template_version_id"]}
        if not isinstance(prompt_ids, dict) or set(prompt_ids) != set(platforms):
            raise PermanentJobError(
                code="generation_prompt_mapping_invalid",
                message="Generation prompt mapping is invalid",
            )
        prompt_checksums = payload.get("platform_prompt_checksums")
        if (
            prompt_checksums is None
            and platforms == ["telegram"]
            and payload.get("platform") == "telegram"
            and payload.get("platform_prompt_checksum")
        ):
            prompt_checksums = {"telegram": payload["platform_prompt_checksum"]}
        if not isinstance(prompt_checksums, dict) or set(prompt_checksums) != set(platforms):
            raise PermanentJobError(
                code="generation_prompt_mapping_invalid",
                message="Generation prompt mapping is invalid",
            )
        story = await context.session.scalar(
            select(Story).where(Story.id == story_revision.story_id, Story.superseded_by_id.is_(None)).with_for_update()
        )
        if story is None:
            raise PermanentJobError(code="generation_story_inactive", message="Active generation story was not found")
        if brand is None:
            raise PermanentJobError(code="generation_brand_profile_missing", message="Brand profile was not found")

        prompts: dict[Platform, PromptTemplateVersion] = {}
        for platform in (item for item in PLATFORM_ORDER if item in platforms):
            try:
                prompt_id = UUID(str(prompt_ids[platform]))
            except TypeError, ValueError:
                raise PermanentJobError(
                    code="generation_prompt_mapping_invalid",
                    message="Generation prompt mapping is invalid",
                ) from None
            active = list(
                await context.session.scalars(
                    select(PromptTemplateVersion)
                    .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.prompt_template_id)
                    .where(
                        PromptTemplateVersion.is_active.is_(True),
                        PromptTemplate.purpose_key == PLATFORM_PROMPT_PURPOSE[platform],
                    )
                    .with_for_update()
                )
            )
            if (
                len(active) != 1
                or active[0].id != prompt_id
                or prompt_checksums.get(platform) != active[0].checksum_sha256
            ):
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
            prompts[platform] = active[0]

        story_citations, evidence = await _locked_story_evidence(context, story_revision)
        _initial_authorized_media, source_media = await _trusted_story_media(context.session, evidence)
        canonical_json = {
            "narrative": story_revision.narrative,
            "facts": story_revision.facts,
            "disagreements": story_revision.disagreements,
            "angles": story_revision.angles,
            "citations": story_revision.citations,
        }
        brand_json = {
            "id": str(brand.id),
            "name": brand.name,
            "output_language": brand.output_language,
            "tone": brand.tone,
            "editorial_rules": brand.editorial_rules,
            "attribution_rules": brand.attribution_rules,
            "default_hashtags": brand.default_hashtags,
            "platform_preferences": brand.platform_preferences,
        }
        first_story_pack_id = await context.session.scalar(
            select(ContentPack.id)
            .join(StoryRevision, StoryRevision.id == ContentPack.story_revision_id)
            .where(StoryRevision.story_id == story_revision.story_id)
            .limit(1)
        )
        pack: ContentPack | None = None
        results: list[dict[str, str]] = []
        completed_platforms: list[Platform] = []
        has_errors = False
        regeneration_context: tuple[UUID, UUID, str] | None = None
        regeneration_fence_owner: RegenerationFenceOwner | None = None
        if payload.get("variant_id") is not None:
            try:
                regeneration_context = (
                    UUID(str(payload["variant_id"])),
                    UUID(str(payload["base_revision_id"])),
                    str(payload["base_content_hash"]),
                )
            except KeyError, TypeError, ValueError:
                raise PermanentJobError(
                    code="generation_regeneration_base_invalid",
                    message="Regeneration base revision is invalid",
                ) from None
            if re.fullmatch(r"[0-9a-f]{64}", regeneration_context[2]) is None:
                raise PermanentJobError(
                    code="generation_regeneration_base_invalid",
                    message="Regeneration base revision is invalid",
                )
        for platform in platforms:
            prompt = prompts[platform]
            telegram_default_direction: Literal["ltr", "rtl"] | None = None
            if platform == "telegram":
                preferences = dict(brand.platform_preferences or {}).get("telegram", {})
                telegram_default_direction = preferences.get(
                    "direction",
                    "rtl" if brand.output_language == "fa" else "ltr",
                )
            input_payload, input_hash = _platform_stage_input(
                platform=platform,
                canonical_story=canonical_json,
                brand_profile=brand_json,
                prompt_checksum=prompt.checksum_sha256,
                provider_profile_id=profile_id,
                instruction=payload.get("instruction"),
                source_media=source_media,
            )

            if platform == "telegram":

                def validate_output(raw: dict[str, Any]) -> TelegramRewriteOutput:
                    return TelegramRewriteOutput.model_validate(raw)
            else:

                def validate_output(raw: dict[str, Any], selected=platform):
                    authored, _issues = _manual_output_with_ordinary_issues(selected, raw)
                    validate_citations(payload_claims(selected, authored), evidence)
                    return authored

            async def before_provider_call(
                selected: Platform = platform,
                expected_prompt_id: UUID = prompt.id,
                expected_prompt_checksum: str = prompt.checksum_sha256,
            ) -> None:
                nonlocal regeneration_fence_owner
                if regeneration_context is None:
                    await _require_exact_active_prompt(
                        context.session,
                        selected,
                        expected_prompt_id,
                        expected_prompt_checksum,
                    )
                else:
                    expected_variant_id, expected_base_id, expected_base_hash = regeneration_context
                    regeneration_fence_owner = await _require_exact_regeneration_dispatch(
                        context.session,
                        platform=selected,
                        variant_id=expected_variant_id,
                        base_revision_id=expected_base_id,
                        base_content_hash=expected_base_hash,
                        prompt_id=expected_prompt_id,
                        prompt_checksum=expected_prompt_checksum,
                        workflow_job_id=job.id,
                        workflow_attempt=job.attempt_count,
                        lease_owner=getattr(job, "lease_owner", None),
                    )

            run, attempt, authored = await _invoke(
                context,
                profile_resolver=profile_resolver,
                profile_id=profile_id,
                prompt=prompt,
                purpose=PLATFORM_PROMPT_PURPOSE[platform],
                story_revision_id=revision_id,
                input_payload=input_payload,
                input_hash=input_hash,
                workflow_job_id=job.id,
                workflow_attempt=job.attempt_count,
                expected_provider_configuration_revision=payload.get("generation_provider_configuration_revision"),
                expected_provider_configuration_checksum=payload.get("generation_provider_configuration_checksum"),
                pack_budget_started_at=budget_started_at,
                prior_pack_cost_usd=cumulative_cost,
                validate_output=validate_output,
                before_provider_call=before_provider_call,
                fault_injector=injector,
            )
            cumulative_cost += Decimal(str((attempt.usage or {}).get("cost_usd", 0)))
            if (
                regeneration_context is not None
                and regeneration_fence_owner is None
                and not isinstance(getattr(run, "output_payload", None), dict)
            ):
                raise RetryableJobError(
                    code="generation_regeneration_checkpoint_unavailable",
                    message="Durable regeneration output is unavailable",
                )
            if (
                regeneration_context is not None
                and regeneration_fence_owner is None
                and not (run.output_payload or {}).get("_artifact")
            ):
                expected_variant_id, expected_base_id, expected_base_hash = regeneration_context
                regeneration_fence_owner = await _require_exact_regeneration_dispatch(
                    context.session,
                    platform=platform,
                    variant_id=expected_variant_id,
                    base_revision_id=expected_base_id,
                    base_content_hash=expected_base_hash,
                    prompt_id=prompt.id,
                    prompt_checksum=prompt.checksum_sha256,
                    workflow_job_id=job.id,
                    workflow_attempt=job.attempt_count,
                    lease_owner=getattr(job, "lease_owner", None),
                )
                await context.session.commit()
            if platform == "telegram":
                content = None
                evidence_map = [item.model_dump(mode="json") for item in story_citations]
                validation_results = None
                platform_has_errors = False
            else:
                content = authored.model_dump(mode="json")
                evidence_map = [item.model_dump(mode="json") for item in ordered_distinct_citations(authored)]
                issues = validate_platform_payload(platform, authored)
                validation_results = revision_gates_from_issues(issues)
                platform_has_errors = any(item.severity == "error" for item in issues)

            locked_story = await context.session.scalar(
                select(Story)
                .where(Story.id == story_revision.story_id, Story.superseded_by_id.is_(None))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if locked_story is None:
                raise PermanentJobError(
                    code="generation_story_inactive",
                    message="Active generation story was not found",
                )
            durable_run = await context.session.scalar(
                select(GenerationRun)
                .where(GenerationRun.id == run.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            artifact = (durable_run.output_payload or {}).get("_artifact") if durable_run else None
            if artifact is not None:
                if not isinstance(artifact, dict) or not {"content_pack_id", "variant_id", "revision_id"}.issubset(
                    artifact
                ):
                    raise NeedsReviewJobError(
                        code="generation_checkpoint_invalid",
                        message="Generation checkpoint is invalid",
                    )
                results.append({key: str(artifact[key]) for key in ("variant_id", "revision_id")})
                has_errors = has_errors or await _artifact_requires_review(
                    context.session,
                    artifact,
                    expected_platform=platform,
                    expected_story_revision_id=revision_id,
                    expected_brand_profile_id=brand.id,
                    expected_attempt_id=attempt.id,
                    authored=authored,
                    expected_content=content,
                    expected_evidence_map=evidence_map,
                    expected_validation_results=validation_results,
                    evidence=evidence,
                    telegram_default_direction=telegram_default_direction,
                    expected_regeneration_base=(
                        (regeneration_context[1], regeneration_context[2]) if regeneration_context is not None else None
                    ),
                )
                pack = await context.session.get(ContentPack, UUID(str(artifact["content_pack_id"])))
                assert pack is not None
                completed_platforms.append(platform)
                await _checkpoint_execution(
                    job,
                    context,
                    result=_pack_job_result(pack.id, completed_platforms, results),
                )
                await context.session.commit()
                continue

            pack = await context.session.scalar(
                select(ContentPack)
                .where(ContentPack.story_revision_id == revision_id, ContentPack.brand_profile_id == brand.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if pack is None:
                pack = ContentPack(
                    id=uuid4(),
                    story_revision_id=revision_id,
                    brand_profile_id=brand.id,
                    status="draft",
                )
                context.session.add(pack)
                await context.session.flush()
                if first_story_pack_id is None:
                    locked_story.status = "drafted"
            variant = await context.session.scalar(
                select(PlatformVariant)
                .where(PlatformVariant.content_pack_id == pack.id, PlatformVariant.platform == platform)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if variant is None:
                variant = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform=platform)
                context.session.add(variant)
                await context.session.flush()
            existing_revision = await context.session.scalar(
                select(PlatformVariantRevision)
                .where(PlatformVariantRevision.generation_attempt_id == attempt.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing_revision is not None:
                raise NeedsReviewJobError(
                    code="generation_checkpoint_invalid",
                    message="Generation revision exists without a durable checkpoint",
                )
            parent = await context.session.scalar(
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
            regeneration_variant_id = payload.get("variant_id")
            if regeneration_variant_id is not None:
                assert regeneration_context is not None
                expected_variant_id, expected_base_id, expected_base_hash = regeneration_context
                if (
                    variant.id != expected_variant_id
                    or parent is None
                    or parent.id != expected_base_id
                    or parent.content_hash != expected_base_hash
                ):
                    raise NeedsReviewJobError(
                        code="generation_regeneration_base_stale",
                        message="Regeneration base revision changed during generation",
                    )
                if regeneration_fence_owner is None:
                    raise RetryableJobError(
                        code="generation_regeneration_fence_unavailable",
                        message="Regeneration fence ownership is unavailable",
                    )
                try:
                    await require_revision_write_allowed(
                        context.session,
                        variant_id=variant.id,
                        owner=regeneration_fence_owner,
                        expected_base_revision_id=expected_base_id,
                        expected_base_content_hash=expected_base_hash,
                    )
                except RegenerationFenceConflict:
                    raise RetryableJobError(
                        code="generation_regeneration_fence_lost",
                        message="Regeneration fence ownership was lost",
                    ) from None
            else:
                try:
                    await require_revision_write_allowed(
                        context.session,
                        variant_id=variant.id,
                    )
                except RegenerationFenceConflict:
                    raise RetryableJobError(
                        code="generation_regeneration_in_progress",
                        message="Variant regeneration is in progress",
                    ) from None
            if platform == "telegram":
                try:
                    assert telegram_default_direction is not None
                    content = assemble_telegram_variant(
                        authored,
                        trusted_parent=parent.content if parent is not None else None,
                        default_direction=telegram_default_direction,
                    ).model_dump(mode="json")
                    telegram_payload = TelegramVariantPayload.model_validate(content)
                    issues = validate_platform_payload("telegram", telegram_payload)
                    validation_results = revision_gates_from_issues(issues)
                    platform_has_errors = any(item.severity == "error" for item in issues)
                except TypeError, ValueError:
                    raise NeedsReviewJobError(
                        code="generation_telegram_parent_invalid",
                        message="Trusted Telegram parent context is invalid",
                    ) from None
            if platform != "telegram":
                fresh_authorized_media, _fresh_source_media = await _trusted_story_media(
                    context.session,
                    evidence,
                    lock_rows=True,
                )
                try:
                    validate_payload_media_assignments(authored, fresh_authorized_media)
                except CitationIntegrityError:
                    raise NeedsReviewJobError(
                        code="media_integrity",
                        message="Generated media assignments failed integrity validation",
                    ) from None
            number = (parent.revision_number if parent is not None else 0) + 1
            existing_revision = PlatformVariantRevision(
                id=uuid4(),
                platform_variant_id=variant.id,
                parent_revision_id=parent.id if parent else None,
                generation_attempt_id=attempt.id,
                revision_number=number,
                content=content,
                content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
                evidence_map=evidence_map,
                validation_results=validation_results,
                approval_state="pending_review",
                created_by="generation",
            )
            context.session.add(existing_revision)
            await context.session.flush()
            has_errors = has_errors or platform_has_errors
            assert durable_run is not None
            durable_run.output_payload = _redacted_dict(
                {
                    **durable_run.output_payload,
                    "_artifact": {
                        "content_pack_id": str(pack.id),
                        "variant_id": str(variant.id),
                        "revision_id": str(existing_revision.id),
                        "platform": platform,
                    },
                }
            )
            results.append({"variant_id": str(variant.id), "revision_id": str(existing_revision.id)})
            completed_platforms.append(platform)
            await _checkpoint_execution(
                job,
                context,
                result=_pack_job_result(pack.id, completed_platforms, results),
            )
            await context.session.commit()

        assert pack is not None
        result = _pack_job_result(pack.id, completed_platforms, results)
        if has_errors:
            await _checkpoint_execution(job, context, result=result)
            raise NeedsReviewJobError(
                code="platform_validation_failed",
                message="Generated platform package requires operator review",
            )
        return result

    return handle


def build_regenerate_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
):
    async def handle(job: JobExecution, context: JobContext) -> dict[str, Any]:
        payload = _job_payload(job)
        variant_id = _required_uuid(payload, "variant_id")
        variant = await context.session.scalar(
            select(PlatformVariant).where(PlatformVariant.id == variant_id).execution_options(populate_existing=True)
        )
        pack = await context.session.get(ContentPack, variant.content_pack_id) if variant else None
        if pack is None:
            raise PermanentJobError(
                code=("generation_variant_missing" if variant is None else "generation_content_pack_missing"),
                message="Regeneration variant context was not found",
            )
        legacy_required = {
            "variant_id",
            "generation_provider_profile_id",
            "platform_prompt_template_version_id",
        }
        legacy_allowed = legacy_required | {"instruction"}
        is_release_three_legacy = legacy_required.issubset(payload) and set(payload).issubset(legacy_allowed)
        current = await context.session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant.id)
            .order_by(
                PlatformVariantRevision.revision_number.desc(),
                PlatformVariantRevision.created_at.desc(),
                PlatformVariantRevision.id.desc(),
            )
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if is_release_three_legacy:
            if variant.platform != "telegram":
                raise PermanentJobError(
                    code="generation_regeneration_legacy_unsupported",
                    message="Legacy regeneration is supported only for Telegram variants",
                )
            prompt_id = _required_uuid(payload, "platform_prompt_template_version_id")
            active = list(
                await context.session.scalars(
                    select(PromptTemplateVersion)
                    .join(PromptTemplate, PromptTemplate.id == PromptTemplateVersion.prompt_template_id)
                    .where(
                        PromptTemplateVersion.is_active.is_(True),
                        PromptTemplate.purpose_key == "telegram_pack",
                    )
                    .execution_options(populate_existing=True)
                )
            )
            if len(active) != 1 or active[0].id != prompt_id:
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
            if current is None:
                raise NeedsReviewJobError(
                    code="generation_regeneration_base_stale",
                    message="Regeneration variant has no current revision",
                )
            payload = {key: value for key, value in payload.items() if key != "platform_prompt_template_version_id"} | {
                "base_revision_id": str(current.id),
                "base_content_hash": current.content_hash,
                "platforms": ["telegram"],
                "platform_prompt_template_version_ids": {"telegram": str(active[0].id)},
                "platform_prompt_checksums": {"telegram": active[0].checksum_sha256},
            }
        else:
            if "platform_prompt_template_version_id" in payload:
                raise PermanentJobError(
                    code="generation_regeneration_legacy_unsupported",
                    message="Legacy regeneration payload is ambiguous",
                )
            _required_uuid(payload, "base_revision_id")
            base_content_hash = payload.get("base_content_hash")
            if not isinstance(base_content_hash, str) or re.fullmatch(r"[0-9a-f]{64}", base_content_hash) is None:
                raise PermanentJobError(
                    code="generation_regeneration_base_invalid",
                    message="Regeneration base revision is invalid",
                )
            if payload.get("platforms") != [variant.platform]:
                raise PermanentJobError(
                    code="generation_regeneration_platform_invalid",
                    message="Regeneration platform does not match the target variant",
                )
            # Do not reject solely because the committed child is now current:
            # a worker may have crashed after the pack handler durably stored
            # its exact artifact. The pack handler either replays that artifact
            # and verifies its immutable parent, or its pre-provider callback
            # rejects a genuinely stale base before another paid call.
        payload.update(
            {"story_revision_id": str(pack.story_revision_id), "brand_profile_id": str(pack.brand_profile_id)}
        )
        delegated_job = await _checkpoint_execution(job, context, payload=payload)
        fence_owner = None
        if (
            isinstance(getattr(job, "attempt_count", None), int)
            and job.attempt_count > 0
            and isinstance(getattr(job, "lease_owner", None), str)
            and bool(job.lease_owner.strip())
        ):
            fence_owner = RegenerationFenceOwner(
                workflow_job_id=job.id,
                workflow_attempt=job.attempt_count,
                lease_owner=job.lease_owner,
            )
        try:
            pack_handler = (
                build_pack_generation_handler(profile_resolver)
                if fault_injector is None
                else build_pack_generation_handler(
                    profile_resolver,
                    fault_injector=fault_injector,
                )
            )
            return await pack_handler(delegated_job, context)
        except Exception:
            if fence_owner is not None:
                await context.session.rollback()
                locked_variant = await context.session.scalar(
                    select(PlatformVariant)
                    .where(PlatformVariant.id == variant.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if locked_variant is not None:
                    await clear_regeneration_fence(
                        context.session,
                        variant_id=variant.id,
                        owner=fence_owner,
                    )
                await context.session.commit()
            raise

    return handle
