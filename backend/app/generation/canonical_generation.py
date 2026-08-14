from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import FaultInjector, NoopFaultInjector
from app.generation.canonical import CanonicalStoryOutput, validate_canonical_output
from app.generation.generation_helpers import (
    _redacted_dict,
    _require_exact_active_canonical_prompt,
    job_payload,
    pack_budget_state,
    required_uuid,
)
from app.generation.models import GenerationAttempt, GenerationRun, PromptTemplate, PromptTemplateVersion
from app.generation.provider_execution import invoke
from app.jobs.errors import NeedsReviewJobError, PermanentJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin
from app.research.models import ResearchRun
from app.stories.evidence import EvidenceRecord, evidence_record_from_snapshot
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


@dataclass(frozen=True, slots=True)
class CanonicalInputs:
    payload: dict[str, Any]
    story: Story
    prompt: PromptTemplateVersion
    profile_id: UUID
    bound_parent: StoryRevision | None
    evidence: dict[UUID, EvidenceRecord]
    evidence_json: list[dict[str, Any]]
    budget_started_at: Any


def build_canonical_generation_handler(
    profile_resolver: Any,
    *,
    fault_injector: FaultInjector | None = None,
):
    handler = partial(
        handle_canonical_generation,
        profile_resolver=profile_resolver,
        fault_injector=fault_injector or NoopFaultInjector(),
    )
    handler.__annotations__ = {
        "job": JobExecution,
        "context": JobContext,
        "return": dict[str, Any],
    }
    return handler


async def handle_canonical_generation(
    job: JobExecution,
    context: JobContext,
    *,
    profile_resolver: Any,
    fault_injector: FaultInjector,
) -> dict[str, Any]:
    inputs = await _load_inputs(job, context)
    run, attempt, output = await _generate(
        job,
        context,
        inputs,
        profile_resolver=profile_resolver,
        fault_injector=fault_injector,
    )
    return await _persist(job, context, inputs, run, attempt, output)


async def _load_inputs(job: JobExecution, context: JobContext) -> CanonicalInputs:
    payload = job_payload(job)
    budget_started_at, _prior_cost = pack_budget_state(job, payload)
    story_id = required_uuid(payload, "story_id")
    prompt_id = required_uuid(payload, "canonical_prompt_template_version_id")
    profile_id = required_uuid(payload, "generation_provider_profile_id")
    story, prompt = await _load_story_and_prompt(context, story_id, prompt_id, payload)
    bound_parent = await _load_bound_parent(context, payload, story_id)
    evidence, evidence_json = await _load_evidence(context, story_id, bound_parent)
    return CanonicalInputs(
        payload=payload,
        story=story,
        prompt=prompt,
        profile_id=profile_id,
        bound_parent=bound_parent,
        evidence=evidence,
        evidence_json=evidence_json,
        budget_started_at=budget_started_at,
    )


async def _load_story_and_prompt(
    context: JobContext,
    story_id: UUID,
    prompt_id: UUID,
    payload: dict[str, Any],
) -> tuple[Story, PromptTemplateVersion]:
    story = await context.session.scalar(
        select(Story).where(Story.id == story_id, Story.superseded_by_id.is_(None)).with_for_update()
    )
    prompt = await context.session.get(PromptTemplateVersion, prompt_id)
    template = await context.session.get(PromptTemplate, prompt.prompt_template_id) if prompt is not None else None
    if story is None:
        raise PermanentJobError(code="generation_story_inactive", message="Active generation story was not found")
    if prompt is None:
        raise PermanentJobError(
            code="generation_canonical_prompt_missing",
            message="Canonical prompt version was not found",
        )
    if template is None or template.purpose_key != "canonical_story":
        raise PermanentJobError(
            code="generation_canonical_prompt_purpose_invalid",
            message="Canonical prompt purpose is invalid",
        )
    checksum = payload.get("canonical_prompt_checksum")
    if not isinstance(checksum, str) or checksum != prompt.checksum_sha256:
        raise PermanentJobError(
            code="generation_canonical_prompt_configuration_invalid",
            message="Canonical prompt configuration is invalid",
        )
    return story, prompt


async def _load_bound_parent(
    context: JobContext,
    payload: dict[str, Any],
    story_id: UUID,
) -> StoryRevision | None:
    bound_parent_id = payload.get("research_result_story_revision_id")
    if bound_parent_id is None:
        return None
    try:
        parsed_parent_id = UUID(str(bound_parent_id))
        parsed_run_id = UUID(str(payload["completed_research_run_id"]))
    except KeyError, TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_research_lineage_invalid",
            message="Bound research revision is invalid",
        ) from None
    parent = await context.session.get(StoryRevision, parsed_parent_id)
    run = await context.session.get(ResearchRun, parsed_run_id)
    if (
        parent is None
        or parent.story_id != story_id
        or run is None
        or run.status != "succeeded"
        or run.story_id != story_id
        or run.result_story_revision_id != parent.id
    ):
        raise NeedsReviewJobError(
            code="generation_research_lineage_invalid",
            message="Bound research revision does not belong to the story",
        )
    return parent


async def _load_evidence(
    context: JobContext,
    story_id: UUID,
    bound_parent: StoryRevision | None,
) -> tuple[dict[UUID, EvidenceRecord], list[dict[str, Any]]]:
    bound_ids = _bound_snapshot_ids(bound_parent)
    statement = select(StoryEvidenceSnapshot).where(StoryEvidenceSnapshot.story_id == story_id)
    if bound_ids is not None:
        statement = statement.where(StoryEvidenceSnapshot.id.in_(bound_ids))
    snapshots = list(
        await context.session.scalars(statement.order_by(StoryEvidenceSnapshot.captured_at, StoryEvidenceSnapshot.id))
    )
    if not snapshots:
        raise NeedsReviewJobError(
            code="generation_evidence_missing",
            message="Canonical generation requires evidence",
        )
    if bound_ids is not None and {item.id for item in snapshots} != bound_ids:
        raise NeedsReviewJobError(
            code="generation_research_evidence_missing",
            message="Bound research evidence is unavailable",
        )
    evidence = {row.id: evidence_record_from_snapshot(row) for row in snapshots}
    projected = [
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
    return evidence, projected


def _bound_snapshot_ids(parent: StoryRevision | None) -> set[UUID] | None:
    if parent is None:
        return None
    try:
        snapshot_ids = {
            UUID(str(item["evidence_snapshot_id"])) for item in parent.citations if item.get("evidence_snapshot_id")
        }
    except AttributeError, TypeError, ValueError:
        raise NeedsReviewJobError(
            code="generation_research_evidence_invalid",
            message="Bound research evidence is invalid",
        ) from None
    if not snapshot_ids:
        raise NeedsReviewJobError(
            code="generation_research_evidence_missing",
            message="Bound research revision has no evidence",
        )
    return snapshot_ids


async def _generate(
    job: JobExecution,
    context: JobContext,
    inputs: CanonicalInputs,
    *,
    profile_resolver: Any,
    fault_injector: FaultInjector,
) -> tuple[GenerationRun, GenerationAttempt, CanonicalStoryOutput]:
    input_hash = sha256_canonical(
        {
            "story_id": str(inputs.story.id),
            "evidence": inputs.evidence_json,
            "prompt_checksum": inputs.prompt.checksum_sha256,
            "provider_profile_id": str(inputs.profile_id),
        }
    )

    def validate(raw: dict[str, Any]) -> CanonicalStoryOutput:
        return validate_canonical_output(CanonicalStoryOutput.model_validate(raw), inputs.evidence)

    async def fence_prompt() -> None:
        await _require_exact_active_canonical_prompt(
            context.session,
            inputs.prompt.id,
            inputs.prompt.checksum_sha256,
        )

    return await invoke(
        context,
        profile_resolver=profile_resolver,
        profile_id=inputs.profile_id,
        prompt=inputs.prompt,
        purpose="canonical_story",
        story_revision_id=None,
        input_payload={
            "story_title": inputs.story.title,
            "evidence_json": json.dumps(inputs.evidence_json, ensure_ascii=False, sort_keys=True),
        },
        input_hash=input_hash,
        workflow_job_id=job.id,
        workflow_attempt=job.attempt_count,
        expected_provider_configuration_revision=inputs.payload.get("generation_provider_configuration_revision"),
        expected_provider_configuration_checksum=inputs.payload.get("generation_provider_configuration_checksum"),
        pack_budget_started_at=inputs.budget_started_at,
        validate_output=validate,
        before_provider_call=fence_prompt,
        fault_injector=fault_injector,
    )


async def _persist(
    job: JobExecution,
    context: JobContext,
    inputs: CanonicalInputs,
    run: GenerationRun,
    attempt: GenerationAttempt,
    output: CanonicalStoryOutput,
) -> dict[str, Any]:
    await _require_active_story(context, inputs.story.id)
    durable_run = await context.session.scalar(
        select(GenerationRun)
        .where(GenerationRun.id == run.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    artifact = (durable_run.output_payload or {}).get("_artifact") if durable_run else None
    if artifact is not None:
        return _checkpoint_result(artifact)
    parent = inputs.bound_parent or await _latest_story_revision(context, inputs.story.id)
    revision = await _create_story_revision(context, inputs.story.id, parent, output)
    queued = await _enqueue_package(job, context, inputs, revision, attempt)
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


async def _require_active_story(context: JobContext, story_id: UUID) -> Story:
    story = await context.session.scalar(
        select(Story)
        .where(Story.id == story_id, Story.superseded_by_id.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if story is None:
        raise PermanentJobError(code="generation_story_inactive", message="Active generation story was not found")
    return story


def _checkpoint_result(artifact: Any) -> dict[str, Any]:
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


async def _latest_story_revision(context: JobContext, story_id: UUID) -> StoryRevision | None:
    return await context.session.scalar(
        select(StoryRevision)
        .where(StoryRevision.story_id == story_id)
        .order_by(StoryRevision.revision_number.desc())
        .with_for_update()
    )


async def _create_story_revision(
    context: JobContext,
    story_id: UUID,
    parent: StoryRevision | None,
    output: CanonicalStoryOutput,
) -> StoryRevision:
    number = (
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
        revision_number=number,
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
    return revision


async def _enqueue_package(
    job: JobExecution,
    context: JobContext,
    inputs: CanonicalInputs,
    revision: StoryRevision,
    attempt: GenerationAttempt,
):
    canonical_cost = Decimal(str((attempt.usage or {}).get("cost_usd", 0)))
    continuation = inputs.payload | {
        "story_revision_id": str(revision.id),
        "generation_budget_started_at": inputs.budget_started_at.isoformat(),
        "generation_budget_cost_usd": str(canonical_cost),
    }
    return await JobRepository(context.session).enqueue_job(
        job_type="content_pack.generate_telegram",
        payload=continuation,
        idempotency_key=f"content-pack-telegram:{job.id}:{revision.id}",
        origin=JobOrigin.AUTOMATION,
        automation_run_id=job.automation_run_id,
        automation_node_run_id=job.automation_node_run_id,
    )
