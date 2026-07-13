from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select

from app.automations.telegram.handlers import sha256_canonical
from app.generation.canonical import CanonicalStoryOutput, validate_canonical_output
from app.generation.default_prompts import prompt_checksum
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
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.telegram_schema import TelegramEvidenceCitation, TelegramRewriteOutput, TelegramVariantContent
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin
from app.research.models import ResearchRun
from app.stories.evidence import EvidenceRecord
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


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
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", str(value).strip().lower()).strip("_.-")
    return normalized[:120] or fallback


def _required_uuid(payload: dict[str, Any], key: str) -> UUID:
    try:
        return UUID(str(payload[key]))
    except KeyError, TypeError, ValueError:
        raise PermanentJobError(
            code="generation_job_payload_invalid",
            message="Generation job payload is invalid",
        ) from None


def _job_payload(job: Any) -> dict[str, Any]:
    if not isinstance(job.payload, dict):
        raise PermanentJobError(
            code="generation_job_payload_invalid",
            message="Generation job payload is invalid",
        )
    return dict(job.payload)


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
) -> tuple[GenerationRun, GenerationAttempt, Any]:
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
        return existing, completed, validate_output(durable_output)
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
            requested_model=resolved.model,
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
        requested_model=resolved.model,
        resolved_model=resolved.model,
        prompt_snapshot=_prompt_snapshot(prompt, messages),
        response_payload={},
        usage={},
        validation_errors=[],
        status="running",
        started_at=now,
    )
    context.session.add(attempt)
    run.request_payload = {
        "stage_key": stage_key,
        "input": input_payload,
        "prompt": _prompt_snapshot(prompt, messages),
        "execution": {
            "workflow_job_id": str(workflow_job_id),
            "workflow_attempt": workflow_attempt,
            "active_attempt_id": str(attempt.id),
        },
    }
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
        },
    )
    provider_completed = False
    try:
        result = await resolved.provider.generate(request)
        provider_completed = True
        validated = validate_output(result.output)
    except Exception as exc:
        await context.session.rollback()
        error_class = getattr(exc, "classification", getattr(exc, "error_class", None))
        provider_code = _safe_error_code(getattr(exc, "code", ""), "generation_provider_failed")
        mapped: RetryableJobError | NeedsReviewJobError | PermanentJobError
        if provider_completed and isinstance(exc, (ValidationError, ValueError)):
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
            mapped = RetryableJobError(
                code=provider_code,
                message="Generation provider call failed",
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
                    current_attempt.status = "failed"
                    current_attempt.error_class = error_class
                    current_attempt.error_code = mapped.code
                    current_attempt.error_message = mapped.message
                    current_attempt.finished_at = datetime.now(UTC)
                    if isinstance(exc, ValidationError):
                        current_attempt.validation_errors = [
                            {
                                "type": item["type"],
                                "loc": [str(part) for part in item["loc"]],
                                "message": item["msg"],
                            }
                            for item in exc.errors(include_input=False, include_url=False)
                        ]
                    current_run.status = "failed"
                    current_run.error_class = error_class
                    current_run.error_code = mapped.code
                    current_run.error_message = mapped.message
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
        current_attempt.response_payload = result.output
        current_attempt.resolved_model = result.resolved_model
        current_attempt.usage = result.usage
        current_attempt.status = "succeeded"
        current_attempt.finished_at = datetime.now(UTC)
        current_run.output_payload = result.output
        current_run.status = "succeeded"
        current_run.finished_at = datetime.now(UTC)
        current_run.error_class = current_run.error_code = current_run.error_message = None
    return current_run, current_attempt, validated


def build_canonical_generation_handler(profile_resolver: Any):
    async def handle(job, context: JobContext) -> dict[str, Any]:
        payload = _job_payload(job)
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
            validate_output=validate_canonical,
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
        continuation = payload | {"story_revision_id": str(revision.id)}
        queued = await JobRepository(context.session).enqueue_job(
            job_type="content_pack.generate_telegram",
            payload=continuation,
            idempotency_key=f"content-pack-telegram:{job.id}:{revision.id}",
            origin=JobOrigin.AUTOMATION,
        )
        assert durable_run is not None
        durable_run.output_payload = {
            **durable_run.output_payload,
            "_artifact": {
                "story_revision_id": str(revision.id),
                "continuation_job_id": str(queued.job.id),
            },
        }
        return {"story_revision_id": str(revision.id), "continuation_job_id": str(queued.job.id)}

    return handle


def build_pack_generation_handler(profile_resolver: Any):
    async def handle(job, context: JobContext) -> dict[str, Any]:
        payload = _job_payload(job)
        revision_id = _required_uuid(payload, "story_revision_id")
        prompt_id = _required_uuid(payload, "platform_prompt_template_version_id")
        brand_id = _required_uuid(payload, "brand_profile_id")
        profile_id = _required_uuid(payload, "generation_provider_profile_id")
        story_revision = await context.session.get(StoryRevision, revision_id)
        prompt = await context.session.get(PromptTemplateVersion, prompt_id)
        template = await context.session.get(PromptTemplate, prompt.prompt_template_id) if prompt is not None else None
        brand = await context.session.get(BrandProfile, brand_id)
        if story_revision is None:
            raise PermanentJobError(
                code="generation_story_revision_missing", message="Canonical story revision was not found"
            )
        story = await context.session.scalar(
            select(Story)
            .where(
                Story.id == story_revision.story_id,
                Story.superseded_by_id.is_(None),
            )
            .with_for_update()
        )
        if story is None:
            raise PermanentJobError(
                code="generation_story_inactive",
                message="Active generation story was not found",
            )
        if prompt is None:
            raise PermanentJobError(
                code="generation_telegram_prompt_missing", message="Telegram prompt version was not found"
            )
        if template is None or template.purpose_key != "telegram_pack":
            raise PermanentJobError(
                code="generation_telegram_prompt_purpose_invalid", message="Telegram prompt purpose is invalid"
            )
        if brand is None:
            raise PermanentJobError(code="generation_brand_profile_missing", message="Brand profile was not found")
        try:
            evidence_map = [
                TelegramEvidenceCitation.model_validate(item).model_dump(mode="json")
                for item in story_revision.citations
            ]
        except TypeError, ValueError:
            raise NeedsReviewJobError(
                code="generation_citations_invalid", message="Canonical story citations are invalid"
            ) from None
        if not evidence_map:
            raise NeedsReviewJobError(
                code="generation_citations_missing", message="Canonical story citations are missing"
            )
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
        input_hash = sha256_canonical(
            {
                "story_revision": canonical_json,
                "brand": brand_json,
                "prompt_checksum": prompt.checksum_sha256,
                "provider_profile_id": str(profile_id),
                "platform": "telegram",
                "instruction": payload.get("instruction"),
            }
        )
        preferences = dict(brand.platform_preferences or {}).get("telegram", {})
        direction = preferences.get("direction", "rtl" if brand.output_language == "fa" else "ltr")

        def validate_telegram(raw: dict[str, Any]) -> TelegramRewriteOutput:
            return TelegramRewriteOutput.model_validate(raw)

        run, attempt, rewrite = await _invoke(
            context,
            profile_resolver=profile_resolver,
            profile_id=profile_id,
            prompt=prompt,
            purpose="telegram_pack",
            story_revision_id=revision_id,
            input_payload={
                "canonical_story_json": json.dumps(canonical_json, ensure_ascii=False, sort_keys=True),
                "brand_profile_json": json.dumps(brand_json, ensure_ascii=False, sort_keys=True),
                "direction": direction,
                "instruction": payload.get("instruction") or "",
            },
            input_hash=input_hash,
            workflow_job_id=job.id,
            workflow_attempt=job.attempt_count,
            validate_output=validate_telegram,
        )
        locked_story = await context.session.scalar(
            select(Story)
            .where(
                Story.id == story_revision.story_id,
                Story.superseded_by_id.is_(None),
            )
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
            if not isinstance(artifact, dict) or not {
                "content_pack_id",
                "variant_id",
                "revision_id",
            }.issubset(artifact):
                raise NeedsReviewJobError(
                    code="generation_checkpoint_invalid",
                    message="Generation checkpoint is invalid",
                )
            return {**artifact, "idempotent": True}
        content = TelegramVariantContent(
            body=rewrite.body,
            parse_mode=rewrite.parse_mode,
            buttons=rewrite.buttons,
            source_item_id=None,
            source_url=None,
            media_policy="omit",
            media_asset_ids=[],
            direction=direction,
            dry_run=False,
        ).model_dump(mode="json")
        first_story_pack_id = await context.session.scalar(
            select(ContentPack.id)
            .join(StoryRevision, StoryRevision.id == ContentPack.story_revision_id)
            .where(StoryRevision.story_id == story_revision.story_id)
            .limit(1)
        )
        pack = await context.session.scalar(
            select(ContentPack)
            .where(ContentPack.story_revision_id == revision_id, ContentPack.brand_profile_id == brand.id)
            .with_for_update()
        )
        if pack is None:
            pack = ContentPack(id=uuid4(), story_revision_id=revision_id, brand_profile_id=brand.id, status="draft")
            context.session.add(pack)
            await context.session.flush()
            if first_story_pack_id is None:
                locked_story.status = "drafted"
        variant = await context.session.scalar(
            select(PlatformVariant)
            .where(PlatformVariant.content_pack_id == pack.id, PlatformVariant.platform == "telegram")
            .with_for_update()
        )
        if variant is None:
            variant = PlatformVariant(id=uuid4(), content_pack_id=pack.id, platform="telegram")
            context.session.add(variant)
            await context.session.flush()
        number = (
            int(
                await context.session.scalar(
                    select(func.coalesce(func.max(PlatformVariantRevision.revision_number), 0)).where(
                        PlatformVariantRevision.platform_variant_id == variant.id
                    )
                )
                or 0
            )
            + 1
        )
        parent = await context.session.scalar(
            select(PlatformVariantRevision)
            .where(PlatformVariantRevision.platform_variant_id == variant.id)
            .order_by(PlatformVariantRevision.revision_number.desc())
            .with_for_update()
        )
        created = PlatformVariantRevision(
            id=uuid4(),
            platform_variant_id=variant.id,
            parent_revision_id=parent.id if parent else None,
            generation_attempt_id=attempt.id,
            revision_number=number,
            content=content,
            content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map}),
            evidence_map=evidence_map,
            validation_results=[{"gate": "telegram_schema", "ok": True}],
            approval_state="pending_review",
            created_by="generation",
        )
        context.session.add(created)
        await context.session.flush()
        assert durable_run is not None
        durable_run.output_payload = {
            **durable_run.output_payload,
            "_artifact": {
                "content_pack_id": str(pack.id),
                "variant_id": str(variant.id),
                "revision_id": str(created.id),
            },
        }
        return {"content_pack_id": str(pack.id), "variant_id": str(variant.id), "revision_id": str(created.id)}

    return handle


def build_regenerate_handler(profile_resolver: Any):
    async def handle(job, context: JobContext) -> dict[str, Any]:
        payload = _job_payload(job)
        variant_id = _required_uuid(payload, "variant_id")
        variant = await context.session.get(PlatformVariant, variant_id)
        pack = await context.session.get(ContentPack, variant.content_pack_id) if variant else None
        if pack is None:
            raise PermanentJobError(
                code=("generation_variant_missing" if variant is None else "generation_content_pack_missing"),
                message="Regeneration variant context was not found",
            )
        payload.update(
            {"story_revision_id": str(pack.story_revision_id), "brand_profile_id": str(pack.brand_profile_id)}
        )
        job.payload = payload
        return await build_pack_generation_handler(profile_resolver)(job, context)

    return handle
