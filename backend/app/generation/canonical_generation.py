from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.automations.telegram.handlers import sha256_canonical
from app.core.faults import FaultInjector, NoopFaultInjector
from app.generation.canonical import CanonicalStoryOutput, validate_canonical_output
from app.generation.generation_helpers import (
    _evidence_record,
    _job_payload,
    _pack_budget_state,
    _redacted_dict,
    _require_exact_active_canonical_prompt,
    _required_uuid,
)
from app.generation.models import (
    GenerationRun,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.generation.provider_execution import _invoke
from app.jobs.errors import NeedsReviewJobError, PermanentJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin
from app.research.models import ResearchRun
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


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
