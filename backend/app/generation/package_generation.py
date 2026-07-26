from __future__ import annotations

import re
from decimal import Decimal
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python
from sqlalchemy import select

from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import FaultInjector, NoopFaultInjector
from app.generation.default_prompts import manual_generation_provider_schema
from app.generation.generation_helpers import (
    _artifact_requires_review,
    _checkpoint_execution,
    _evidence_record,
    _job_payload,
    _pack_budget_state,
    _pack_job_result,
    _platform_stage_input,
    _redacted_dict,
    _require_exact_active_prompt,
    _require_exact_regeneration_dispatch,
    _required_uuid,
    require_prompt_integrity,
)
from app.generation.models import (
    BrandProfile,
    ContentPack,
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
from app.generation.provider_execution import _invoke
from app.generation.revision_fence import (
    RegenerationFenceConflict,
    RegenerationFenceOwner,
    require_revision_write_allowed,
)
from app.generation.telegram_schema import TelegramRewriteOutput, assemble_telegram_variant
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.types import JobExecution
from app.research.citations import CitationIntegrityError, validate_citations
from app.research.schemas import CitationRef, Claim
from app.stories.evidence import EvidenceRecord
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision
from app.stories.states import DRAFTED, decide_story_transition
from app.workflows.states import require_content_pack_transition


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
            cumulative_cost += Decimal(str((getattr(attempt, "usage", None) or {}).get("cost_usd", 0)))
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
                    trusted_media_loader=_trusted_story_media,
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
                    transition = decide_story_transition(locked_story.status, DRAFTED)
                    if not transition.allowed:
                        raise NeedsReviewJobError(
                            code="story_transition_invalid",
                            message="Story cannot enter drafted state",
                        )
                    locked_story.status = DRAFTED
            elif getattr(pack, "status", "draft") != "draft":
                pack.status = require_content_pack_transition(pack.status, "draft")
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
