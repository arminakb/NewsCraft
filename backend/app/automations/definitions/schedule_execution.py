from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select

from app.automations.canonical_json import sha256_canonical
from app.automations.definitions.artifacts import make_artifact, summary_with_artifact
from app.automations.definitions.collection_execution import (
    COLLECTION_ARTICLE_ADDED_TRIGGER,
    handle_collection_article_added,
)
from app.automations.definitions.compiler import verify_compiled_plan
from app.automations.definitions.execution import require_exact_generation_prompts
from app.automations.definitions.models import Automation, AutomationNodeRun, AutomationRun, AutomationVersion
from app.automations.definitions.schemas import WorkflowGraphV1
from app.automations.definitions.source_events import SOURCE_ITEM_CREATED_TRIGGER
from app.automations.definitions.source_execution import handle_new_source_item
from app.db.models import ContentItem
from app.generation.commands import GeneratePackRequest
from app.generation.editorial_service import EditorialService
from app.generation.errors import InvalidGenerationRequest
from app.jobs.errors import PermanentJobError
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


class ScheduledAutomationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    automation_id: UUID
    automation_version_id: UUID


def _stage(plan: Any, node_type: str) -> Any | None:
    return next((item for item in plan.stages if item.node_type == node_type), None)


def _node_map(plan: Any) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for stage in plan.stages:
        output.setdefault(stage.node_type, []).append(stage.node_id)
    return output


async def _select_revisions(context: JobContext, config: dict[str, object]) -> list[StoryRevision]:
    statement = (
        select(
            Story.id,
            func.max(ContentItem.sort_at).label("selected_sort"),
            func.max(ContentItem.score).label("selected_score"),
        )
        .join(StoryEvidenceSnapshot, StoryEvidenceSnapshot.story_id == Story.id)
        .join(ContentItem, ContentItem.id == StoryEvidenceSnapshot.content_item_id)
        .where(Story.superseded_by_id.is_(None))
        .group_by(Story.id)
    )
    raw_source_ids = config.get("source_ids")
    raw_languages = config.get("languages")
    raw_topics = config.get("topics")
    raw_content_types = config.get("content_types")
    source_ids = [UUID(str(item)) for item in raw_source_ids] if isinstance(raw_source_ids, list) else []
    languages = [str(item) for item in raw_languages] if isinstance(raw_languages, list) else []
    topics = [str(item) for item in raw_topics] if isinstance(raw_topics, list) else []
    content_types = [str(item) for item in raw_content_types] if isinstance(raw_content_types, list) else []
    if source_ids:
        statement = statement.where(ContentItem.primary_source_id.in_(source_ids))
    if languages:
        statement = statement.where(ContentItem.language_code.in_(languages))
    if topics:
        statement = statement.where(ContentItem.canonical_classification["category"].astext.in_(topics))
    if content_types:
        statement = statement.where(ContentItem.content_type.in_(content_types))
    if config.get("minimum_score") is not None:
        statement = statement.where(ContentItem.score >= int(str(config["minimum_score"])))
    if config.get("require_media") is True:
        statement = statement.where(ContentItem.primary_image_id.is_not(None))
    ordering = str(config.get("sort") or "newest")
    if ordering == "oldest":
        statement = statement.order_by(func.max(ContentItem.sort_at), Story.id)
    elif ordering == "score":
        statement = statement.order_by(func.max(ContentItem.score).desc(), Story.id)
    else:
        statement = statement.order_by(func.max(ContentItem.sort_at).desc(), Story.id)
    selected = await context.session.execute(statement.limit(int(str(config.get("max_count") or 20))))
    selected_ids = [row.id for row in selected]
    if not selected_ids:
        return []
    latest = list(
        await context.session.scalars(
            select(StoryRevision)
            .distinct(StoryRevision.story_id)
            .where(StoryRevision.story_id.in_(selected_ids))
            .order_by(StoryRevision.story_id, StoryRevision.revision_number.desc(), StoryRevision.id.desc())
        )
    )
    by_story = {item.story_id: item for item in latest}
    return [by_story[item] for item in selected_ids if item in by_story]


def build_scheduled_automation_handler(profile_resolver: Any) -> JobHandler:
    async def handle(job: JobExecution, context: JobContext) -> dict[str, Any]:
        if job_payload_copy(job).get("trigger_kind") == COLLECTION_ARTICLE_ADDED_TRIGGER:
            return await handle_collection_article_added(job, context, profile_resolver=profile_resolver)
        if job_payload_copy(job).get("trigger_kind") == SOURCE_ITEM_CREATED_TRIGGER:
            return await handle_new_source_item(job, context)
        try:
            payload = ScheduledAutomationPayload.model_validate(job_payload_copy(job))
        except ValidationError as exc:
            raise PermanentJobError(
                code="automation_schedule_payload_invalid",
                message="Scheduled Automation payload is invalid",
            ) from exc

        automation = await context.session.scalar(
            select(Automation).where(Automation.id == payload.automation_id).with_for_update()
        )
        control = await context.session.get(AutomationControl, "global")
        if automation is None or automation.lifecycle != "active":
            return {"outcome": "inactive", "run_ids": []}
        if control is not None and control.global_pause:
            return {"outcome": "paused", "run_ids": []}
        if automation.active_version_id != payload.automation_version_id:
            return {"outcome": "stale_version", "run_ids": []}
        version = await context.session.get(AutomationVersion, payload.automation_version_id)
        if version is None:
            return {"outcome": "stale_version", "run_ids": []}
        replayed_runs = list(
            await context.session.scalars(
                select(AutomationRun).where(
                    AutomationRun.trigger_metadata["schedule_job_id"].astext == str(job.id)
                )
            )
        )
        if replayed_runs:
            return {"outcome": "replayed", "run_ids": [str(item.id) for item in replayed_runs]}
        graph = WorkflowGraphV1.model_validate(version.graph)
        plan = verify_compiled_plan(graph, version.compiled_plan)
        trigger = _stage(plan, "schedule")
        selection = _stage(plan, "select_content")
        generation = _stage(plan, "generate_content_pack")
        research = _stage(plan, "research")
        if trigger is None or selection is None or generation is None:
            raise PermanentJobError(
                code="automation_schedule_plan_invalid",
                message="Scheduled Automation plan is not executable",
            )
        try:
            await require_exact_generation_prompts(context.session, generate_config=generation.config)
            revisions = await _select_revisions(context, selection.config)
        except (InvalidGenerationRequest, ValueError) as exc:
            raise PermanentJobError(
                code="automation_schedule_resource_unavailable",
                message="Scheduled Automation resources are unavailable",
            ) from exc

        now = datetime.now(UTC)
        run_ids: list[str] = []
        for revision in revisions:
            run_key = f"automation-schedule:{job.id}:{revision.id}"
            existing = await context.session.scalar(
                select(AutomationRun).where(AutomationRun.idempotency_key == run_key)
            )
            if existing is not None:
                run_ids.append(str(existing.id))
                continue
            dry_run = bool(control.dry_run) if control is not None else False
            run_id = uuid4()
            schedule_artifact = make_artifact(
                kind="schedule_event",
                capabilities=["structured", "schedule-context"],
                payload={"scheduled_for": (job.scheduled_for or job.created_at).isoformat()},
                source_node_id=trigger.node_id,
                workflow_id=str(automation.id),
                workflow_version_id=str(version.id),
                run_id=str(run_id),
                trigger_type="schedule",
                occurred_at=job.scheduled_for or job.created_at,
            )
            selection_artifact = make_artifact(
                kind="article",
                capabilities=["textual", "structured", "article", "reviewable", "generatable"],
                payload={"story_revision_id": str(revision.id), "story_id": str(revision.story_id)},
                source_node_id=selection.node_id,
                workflow_id=str(automation.id),
                workflow_version_id=str(version.id),
                run_id=str(run_id),
                trigger_type="schedule",
                occurred_at=job.scheduled_for or job.created_at,
            )
            run = AutomationRun(
                id=run_id,
                automation_id=automation.id,
                automation_version_id=version.id,
                trigger_kind="schedule",
                trigger_metadata={
                    "schedule_job_id": str(job.id),
                    "scheduled_for": (job.scheduled_for or job.created_at).isoformat(),
                    "story_revision_id": str(revision.id),
                },
                dry_run=dry_run,
                status="queued",
                current_node_id=research.node_id if research is not None else generation.node_id,
                resource_snapshot={
                    "automation_version": version.version,
                    "graph_hash": version.graph_hash,
                    "compiler_version": plan.compiler_version,
                    "plan_hash": plan.plan_hash,
                    "required_resources": list(plan.required_resources),
                    "node_ids_by_type": _node_map(plan),
                    "node_types_by_id": {stage.node_id: stage.node_type for stage in plan.stages},
                    "node_order": [stage.node_id for stage in plan.stages],
                    "current_artifact": selection_artifact.model_dump(mode="json"),
                    "selected_story_revision_id": str(revision.id),
                },
                idempotency_key=run_key,
                request_hash=sha256_canonical({"job_id": job.id, "story_revision_id": revision.id}, default=str),
                started_at=now,
            )
            context.session.add(run)
            await context.session.flush()
            nodes: dict[str, AutomationNodeRun] = {}
            for stage in plan.stages:
                succeeded = stage.node_id in {trigger.node_id, selection.node_id}
                skipped = dry_run and stage.node_id in plan.publishing_node_ids
                status = "succeeded" if succeeded else "skipped" if skipped else "pending"
                node = AutomationNodeRun(
                    id=uuid4(),
                    automation_run_id=run.id,
                    node_id=stage.node_id,
                    status=status,
                    started_at=now if succeeded else None,
                    finished_at=now if succeeded or skipped else None,
                    input_summary={"story_revision_id": str(revision.id)} if succeeded else {},
                    output_summary=(
                        {"reason": "dry_run_publication_disabled"}
                        if skipped
                        else summary_with_artifact({}, schedule_artifact)
                        if stage.node_id == trigger.node_id
                        else summary_with_artifact({}, selection_artifact)
                        if stage.node_id == selection.node_id
                        else {}
                    ),
                )
                context.session.add(node)
                nodes[stage.node_id] = node
            await context.session.flush()
            request = GeneratePackRequest(
                brand_profile_id=UUID(str(generation.config["editorial_profile_id"])),
                platforms=list(generation.config.get("platforms") or ["telegram"]),  # type: ignore[arg-type]
                generation_provider_profile_id=UUID(str(generation.config["provider_profile_id"])),
                research_mode=(str(research.config.get("mode")) if research is not None else "off"),  # type: ignore[arg-type]
                research_provider_profile_id=(
                    UUID(str(research.config["provider_profile_id"])) if research is not None else None
                ),
            )
            try:
                accepted = await EditorialService(
                    context.session,
                    profile_resolver=profile_resolver,
                ).request_content_pack(revision.story_id, request)
            except InvalidGenerationRequest as exc:
                raise PermanentJobError(
                    code="automation_schedule_generation_rejected",
                    message="Scheduled generation request was rejected",
                ) from exc
            child = await context.session.get(WorkflowJob, accepted.job_id)
            if child is None:
                raise PermanentJobError(
                    code="automation_schedule_job_missing",
                    message="Scheduled generation job was not created",
                )
            if child.automation_run_id is not None and child.automation_run_id != run.id:
                raise PermanentJobError(
                    code="automation_schedule_generation_already_owned",
                    message="Scheduled generation request is already owned by another Automation run",
                )
            target = (
                nodes[research.node_id]
                if research is not None and child.job_type == "research_story"
                else nodes[generation.node_id]
            )
            target.status = "queued"
            target.workflow_job_id = child.id
            child.automation_run_id = run.id
            child.automation_node_run_id = target.id
            run.root_workflow_job_id = child.id
            context.session.add(
                WorkflowEvent(
                    workflow_job_id=child.id,
                    event_type="automation.run.started",
                    actor="scheduler",
                    event_data={
                        "automation_id": str(automation.id),
                        "automation_run_id": str(run.id),
                        "automation_version": version.version,
                        "dry_run": dry_run,
                    },
                )
            )
            run_ids.append(str(run.id))
        await context.session.commit()
        return {"outcome": "started" if run_ids else "empty_selection", "run_ids": run_ids}

    return handle


__all__ = ["ScheduledAutomationPayload", "build_scheduled_automation_handler"]
