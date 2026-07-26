from __future__ import annotations

from decimal import Decimal
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import FaultInjector, NoopFaultInjector
from app.generation import package_inputs
from app.generation.generation_helpers import (
    _artifact_requires_review,
    _checkpoint_execution,
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
from app.generation.multiplatform import PLATFORM_ORDER, PLATFORM_PROMPT_PURPOSE
from app.generation.package_evidence import (
    locked_story_evidence as _locked_story_evidence,
)
from app.generation.platform_media import (
    trusted_story_media as _trusted_story_media,
)
from app.generation.platform_media import (
    validate_payload_media_assignments,
)
from app.generation.platform_output import (
    _manual_output_with_ordinary_issues as _manual_output_with_ordinary_issues,
)
from app.generation.platform_output import (
    validate_provider_output as _validate_provider_output,
)
from app.generation.platform_schemas import (
    Platform,
    TelegramVariantPayload,
)
from app.generation.platform_validation import (
    revision_gates_from_issues,
    validate_platform_payload,
)
from app.generation.provider_execution import _invoke
from app.generation.revision_fence import (
    RegenerationFenceConflict,
    require_revision_write_allowed,
)
from app.generation.telegram_schema import assemble_telegram_variant
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.types import JobExecution
from app.research.citations import CitationIntegrityError
from app.stories.models import Story, StoryRevision
from app.stories.states import DRAFTED, decide_story_transition
from app.workflows.states import require_content_pack_transition


async def _initial_prompts(
    context: JobContext,
    *,
    platforms: list[Platform],
    prompt_ids: dict[str, Any],
    checksums: dict[str, Any],
) -> dict[Platform, PromptTemplateVersion]:
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
        if len(active) != 1 or active[0].id != prompt_id or checksums.get(platform) != active[0].checksum_sha256:
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
    return prompts


async def _load_pack_inputs(
    job: JobExecution,
    context: JobContext,
) -> tuple[package_inputs.PackInputs, Decimal]:
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
    platforms = package_inputs.requested_platforms(payload)
    prompt_ids, checksums = package_inputs.prompt_mappings(payload, platforms)
    story = await context.session.scalar(
        select(Story).where(Story.id == story_revision.story_id, Story.superseded_by_id.is_(None)).with_for_update()
    )
    if story is None:
        raise PermanentJobError(
            code="generation_story_inactive",
            message="Active generation story was not found",
        )
    if brand is None:
        raise PermanentJobError(
            code="generation_brand_profile_missing",
            message="Brand profile was not found",
        )
    prompts = await _initial_prompts(
        context,
        platforms=platforms,
        prompt_ids=prompt_ids,
        checksums=checksums,
    )
    story_citations, evidence = await _locked_story_evidence(context, story_revision)
    _authorized_media, source_media = await _trusted_story_media(context.session, evidence)
    first_story_pack_id = await context.session.scalar(
        select(ContentPack.id)
        .join(StoryRevision, StoryRevision.id == ContentPack.story_revision_id)
        .where(StoryRevision.story_id == story_revision.story_id)
        .limit(1)
    )
    return (
        package_inputs.PackInputs(
            payload=payload,
            budget_started_at=budget_started_at,
            story_revision=story_revision,
            brand=brand,
            profile_id=profile_id,
            platforms=platforms,
            prompts=prompts,
            story_citations=story_citations,
            evidence=evidence,
            source_media=source_media,
            canonical_json=package_inputs.canonical_json(story_revision),
            brand_json=package_inputs.brand_json(brand),
            first_story_pack_id=first_story_pack_id,
            regeneration=package_inputs.regeneration_context(payload),
        ),
        cumulative_cost,
    )


async def _before_platform_provider_call(
    *,
    context: JobContext,
    job: JobExecution,
    inputs: package_inputs.PackInputs,
    progress: package_inputs.PackProgress,
    platform: Platform,
    prompt: PromptTemplateVersion,
) -> None:
    if inputs.regeneration is None:
        await _require_exact_active_prompt(
            context.session,
            platform,
            prompt.id,
            prompt.checksum_sha256,
        )
        return
    regeneration = inputs.regeneration
    progress.regeneration_owner = await _require_exact_regeneration_dispatch(
        context.session,
        platform=platform,
        variant_id=regeneration.variant_id,
        base_revision_id=regeneration.base_revision_id,
        base_content_hash=regeneration.base_content_hash,
        prompt_id=prompt.id,
        prompt_checksum=prompt.checksum_sha256,
        workflow_job_id=job.id,
        workflow_attempt=job.attempt_count,
        lease_owner=getattr(job, "lease_owner", None),
    )


async def _ensure_regeneration_fence(
    job: JobExecution,
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    progress: package_inputs.PackProgress,
    platform: Platform,
    prompt: PromptTemplateVersion,
    run: GenerationRun,
) -> None:
    if inputs.regeneration is None or progress.regeneration_owner is not None:
        return
    output_payload = getattr(run, "output_payload", None)
    if not isinstance(output_payload, dict):
        raise RetryableJobError(
            code="generation_regeneration_checkpoint_unavailable",
            message="Durable regeneration output is unavailable",
        )
    if output_payload.get("_artifact"):
        return
    regeneration = inputs.regeneration
    progress.regeneration_owner = await _require_exact_regeneration_dispatch(
        context.session,
        platform=platform,
        variant_id=regeneration.variant_id,
        base_revision_id=regeneration.base_revision_id,
        base_content_hash=regeneration.base_content_hash,
        prompt_id=prompt.id,
        prompt_checksum=prompt.checksum_sha256,
        workflow_job_id=job.id,
        workflow_attempt=job.attempt_count,
        lease_owner=getattr(job, "lease_owner", None),
    )
    await context.session.commit()


async def _generate_platform(
    job: JobExecution,
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    progress: package_inputs.PackProgress,
    profile_resolver: Any,
    injector: FaultInjector,
    platform: Platform,
) -> package_inputs.GeneratedPlatform:
    prompt = inputs.prompts[platform]
    input_payload, input_hash = _platform_stage_input(
        platform=platform,
        canonical_story=inputs.canonical_json,
        brand_profile=inputs.brand_json,
        prompt_checksum=prompt.checksum_sha256,
        provider_profile_id=inputs.profile_id,
        instruction=inputs.payload.get("instruction"),
        source_media=inputs.source_media,
    )
    run, attempt, authored = await _invoke(
        context,
        profile_resolver=profile_resolver,
        profile_id=inputs.profile_id,
        prompt=prompt,
        purpose=PLATFORM_PROMPT_PURPOSE[platform],
        story_revision_id=inputs.story_revision.id,
        input_payload=input_payload,
        input_hash=input_hash,
        workflow_job_id=job.id,
        workflow_attempt=job.attempt_count,
        expected_provider_configuration_revision=inputs.payload.get("generation_provider_configuration_revision"),
        expected_provider_configuration_checksum=inputs.payload.get("generation_provider_configuration_checksum"),
        pack_budget_started_at=inputs.budget_started_at,
        prior_pack_cost_usd=progress.cumulative_cost,
        validate_output=partial(
            _validate_provider_output,
            platform=platform,
            evidence=inputs.evidence,
        ),
        before_provider_call=partial(
            _before_platform_provider_call,
            context=context,
            job=job,
            inputs=inputs,
            progress=progress,
            platform=platform,
            prompt=prompt,
        ),
        fault_injector=injector,
    )
    progress.cumulative_cost += Decimal(str((getattr(attempt, "usage", None) or {}).get("cost_usd", 0)))
    await _ensure_regeneration_fence(
        job,
        context,
        inputs=inputs,
        progress=progress,
        platform=platform,
        prompt=prompt,
        run=run,
    )
    content, evidence_map, validation_results, has_errors = package_inputs.revision_material(
        platform,
        authored,
        inputs.story_citations,
    )
    return package_inputs.GeneratedPlatform(
        platform=platform,
        prompt=prompt,
        default_direction=package_inputs.telegram_direction(platform, inputs.brand),
        run=run,
        attempt=attempt,
        authored=authored,
        content=content,
        evidence_map=evidence_map,
        validation_results=validation_results,
        has_errors=has_errors,
    )


async def _locked_story_and_run(
    context: JobContext,
    inputs: package_inputs.PackInputs,
    generated: package_inputs.GeneratedPlatform,
) -> tuple[Story, GenerationRun | None]:
    story = await context.session.scalar(
        select(Story)
        .where(
            Story.id == inputs.story_revision.story_id,
            Story.superseded_by_id.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if story is None:
        raise PermanentJobError(
            code="generation_story_inactive",
            message="Active generation story was not found",
        )
    run = await context.session.scalar(
        select(GenerationRun)
        .where(GenerationRun.id == generated.run.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return story, run


def _durable_artifact(run: GenerationRun | None) -> dict[str, Any] | None:
    artifact = (run.output_payload or {}).get("_artifact") if run else None
    if artifact is None:
        return None
    if not isinstance(artifact, dict) or not {
        "content_pack_id",
        "variant_id",
        "revision_id",
    }.issubset(artifact):
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation checkpoint is invalid",
        )
    return artifact


async def _checkpoint_platform(
    job: JobExecution,
    context: JobContext,
    progress: package_inputs.PackProgress,
) -> None:
    assert progress.pack is not None
    await _checkpoint_execution(
        job,
        context,
        result=_pack_job_result(
            progress.pack.id,
            progress.completed_platforms,
            progress.results,
        ),
    )
    await context.session.commit()


async def _reuse_artifact(
    job: JobExecution,
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    progress: package_inputs.PackProgress,
    generated: package_inputs.GeneratedPlatform,
    artifact: dict[str, Any],
) -> None:
    progress.results.append({key: str(artifact[key]) for key in ("variant_id", "revision_id")})
    regeneration_base = (
        (
            inputs.regeneration.base_revision_id,
            inputs.regeneration.base_content_hash,
        )
        if inputs.regeneration is not None
        else None
    )
    progress.has_errors = progress.has_errors or await _artifact_requires_review(
        context.session,
        artifact,
        expected_platform=generated.platform,
        expected_story_revision_id=inputs.story_revision.id,
        expected_brand_profile_id=inputs.brand.id,
        expected_attempt_id=generated.attempt.id,
        authored=generated.authored,
        expected_content=generated.content,
        expected_evidence_map=generated.evidence_map,
        expected_validation_results=generated.validation_results,
        evidence=inputs.evidence,
        telegram_default_direction=generated.default_direction,
        expected_regeneration_base=regeneration_base,
        trusted_media_loader=_trusted_story_media,
    )
    progress.pack = await context.session.get(
        ContentPack,
        UUID(str(artifact["content_pack_id"])),
    )
    assert progress.pack is not None
    progress.completed_platforms.append(generated.platform)
    await _checkpoint_platform(job, context, progress)


async def _draft_pack(
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    story: Story,
) -> ContentPack:
    pack = await context.session.scalar(
        select(ContentPack)
        .where(
            ContentPack.story_revision_id == inputs.story_revision.id,
            ContentPack.brand_profile_id == inputs.brand.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if pack is None:
        pack = ContentPack(
            id=uuid4(),
            story_revision_id=inputs.story_revision.id,
            brand_profile_id=inputs.brand.id,
            status="draft",
        )
        context.session.add(pack)
        await context.session.flush()
        if inputs.first_story_pack_id is None:
            transition = decide_story_transition(story.status, DRAFTED)
            if not transition.allowed:
                raise NeedsReviewJobError(
                    code="story_transition_invalid",
                    message="Story cannot enter drafted state",
                )
            story.status = DRAFTED
    elif getattr(pack, "status", "draft") != "draft":
        pack.status = require_content_pack_transition(pack.status, "draft")
    return pack


async def _platform_variant(
    context: JobContext,
    *,
    pack: ContentPack,
    platform: Platform,
) -> PlatformVariant:
    variant = await context.session.scalar(
        select(PlatformVariant)
        .where(
            PlatformVariant.content_pack_id == pack.id,
            PlatformVariant.platform == platform,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if variant is None:
        variant = PlatformVariant(
            id=uuid4(),
            content_pack_id=pack.id,
            platform=platform,
        )
        context.session.add(variant)
        await context.session.flush()
    return variant


async def _revision_parent(
    context: JobContext,
    *,
    variant: PlatformVariant,
    attempt_id: UUID,
) -> PlatformVariantRevision | None:
    existing = await context.session.scalar(
        select(PlatformVariantRevision)
        .where(PlatformVariantRevision.generation_attempt_id == attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        raise NeedsReviewJobError(
            code="generation_checkpoint_invalid",
            message="Generation revision exists without a durable checkpoint",
        )
    return await context.session.scalar(
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


async def _require_variant_write(
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    progress: package_inputs.PackProgress,
    variant: PlatformVariant,
    parent: PlatformVariantRevision | None,
) -> None:
    regeneration = inputs.regeneration
    if regeneration is None:
        try:
            await require_revision_write_allowed(context.session, variant_id=variant.id)
        except RegenerationFenceConflict:
            raise RetryableJobError(
                code="generation_regeneration_in_progress",
                message="Variant regeneration is in progress",
            ) from None
        return
    if (
        variant.id != regeneration.variant_id
        or parent is None
        or parent.id != regeneration.base_revision_id
        or parent.content_hash != regeneration.base_content_hash
    ):
        raise NeedsReviewJobError(
            code="generation_regeneration_base_stale",
            message="Regeneration base revision changed during generation",
        )
    if progress.regeneration_owner is None:
        raise RetryableJobError(
            code="generation_regeneration_fence_unavailable",
            message="Regeneration fence ownership is unavailable",
        )
    try:
        await require_revision_write_allowed(
            context.session,
            variant_id=variant.id,
            owner=progress.regeneration_owner,
            expected_base_revision_id=regeneration.base_revision_id,
            expected_base_content_hash=regeneration.base_content_hash,
        )
    except RegenerationFenceConflict:
        raise RetryableJobError(
            code="generation_regeneration_fence_lost",
            message="Regeneration fence ownership was lost",
        ) from None


async def _materialize_revision(
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    generated: package_inputs.GeneratedPlatform,
    parent: PlatformVariantRevision | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    if generated.platform == "telegram":
        try:
            assert generated.default_direction is not None
            content = assemble_telegram_variant(
                generated.authored,
                trusted_parent=parent.content if parent is not None else None,
                default_direction=generated.default_direction,
            ).model_dump(mode="json")
            payload = TelegramVariantPayload.model_validate(content)
            issues = validate_platform_payload("telegram", payload)
        except TypeError, ValueError:
            raise NeedsReviewJobError(
                code="generation_telegram_parent_invalid",
                message="Trusted Telegram parent context is invalid",
            ) from None
        return (
            content,
            revision_gates_from_issues(issues),
            any(item.severity == "error" for item in issues),
        )
    authorized_media, _source_media = await _trusted_story_media(
        context.session,
        inputs.evidence,
        lock_rows=True,
    )
    try:
        validate_payload_media_assignments(generated.authored, authorized_media)
    except CitationIntegrityError:
        raise NeedsReviewJobError(
            code="media_integrity",
            message="Generated media assignments failed integrity validation",
        ) from None
    assert generated.content is not None
    assert generated.validation_results is not None
    return generated.content, generated.validation_results, generated.has_errors


async def _persist_new_artifact(
    job: JobExecution,
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    progress: package_inputs.PackProgress,
    generated: package_inputs.GeneratedPlatform,
    story: Story,
    durable_run: GenerationRun | None,
) -> None:
    pack = await _draft_pack(context, inputs=inputs, story=story)
    variant = await _platform_variant(
        context,
        pack=pack,
        platform=generated.platform,
    )
    parent = await _revision_parent(
        context,
        variant=variant,
        attempt_id=generated.attempt.id,
    )
    await _require_variant_write(
        context,
        inputs=inputs,
        progress=progress,
        variant=variant,
        parent=parent,
    )
    content, validation_results, has_errors = await _materialize_revision(
        context,
        inputs=inputs,
        generated=generated,
        parent=parent,
    )
    revision = PlatformVariantRevision(
        id=uuid4(),
        platform_variant_id=variant.id,
        parent_revision_id=parent.id if parent else None,
        generation_attempt_id=generated.attempt.id,
        revision_number=(parent.revision_number if parent is not None else 0) + 1,
        content=content,
        content_hash=sha256_canonical({"content": content, "evidence_map": generated.evidence_map}),
        evidence_map=generated.evidence_map,
        validation_results=validation_results,
        approval_state="pending_review",
        created_by="generation",
    )
    context.session.add(revision)
    await context.session.flush()
    assert durable_run is not None
    durable_run.output_payload = _redacted_dict(
        {
            **durable_run.output_payload,
            "_artifact": {
                "content_pack_id": str(pack.id),
                "variant_id": str(variant.id),
                "revision_id": str(revision.id),
                "platform": generated.platform,
            },
        }
    )
    progress.pack = pack
    progress.has_errors = progress.has_errors or has_errors
    progress.results.append({"variant_id": str(variant.id), "revision_id": str(revision.id)})
    progress.completed_platforms.append(generated.platform)
    await _checkpoint_platform(job, context, progress)


async def _process_platform(
    job: JobExecution,
    context: JobContext,
    *,
    inputs: package_inputs.PackInputs,
    progress: package_inputs.PackProgress,
    profile_resolver: Any,
    injector: FaultInjector,
    platform: Platform,
) -> None:
    generated = await _generate_platform(
        job,
        context,
        inputs=inputs,
        progress=progress,
        profile_resolver=profile_resolver,
        injector=injector,
        platform=platform,
    )
    story, durable_run = await _locked_story_and_run(context, inputs, generated)
    artifact = _durable_artifact(durable_run)
    if artifact is not None:
        await _reuse_artifact(
            job,
            context,
            inputs=inputs,
            progress=progress,
            generated=generated,
            artifact=artifact,
        )
        return
    await _persist_new_artifact(
        job,
        context,
        inputs=inputs,
        progress=progress,
        generated=generated,
        story=story,
        durable_run=durable_run,
    )


async def handle_pack_generation(
    job: JobExecution,
    context: JobContext,
    *,
    profile_resolver: Any,
    injector: FaultInjector,
) -> dict[str, Any]:
    inputs, cumulative_cost = await _load_pack_inputs(job, context)
    progress = package_inputs.PackProgress(cumulative_cost=cumulative_cost)
    for platform in inputs.platforms:
        await _process_platform(
            job,
            context,
            inputs=inputs,
            progress=progress,
            profile_resolver=profile_resolver,
            injector=injector,
            platform=platform,
        )
    assert progress.pack is not None
    result = _pack_job_result(
        progress.pack.id,
        progress.completed_platforms,
        progress.results,
    )
    if progress.has_errors:
        await _checkpoint_execution(job, context, result=result)
        raise NeedsReviewJobError(
            code="platform_validation_failed",
            message="Generated platform package requires operator review",
        )
    return result


def build_pack_generation_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
):
    return partial(
        handle_pack_generation,
        profile_resolver=profile_resolver,
        injector=fault_injector if fault_injector is not None else NoopFaultInjector(),
    )
