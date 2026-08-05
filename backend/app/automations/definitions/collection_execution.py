from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.automations.definitions.collection_events import (
    COLLECTION_ARTICLE_ADDED_EVENT,
    COLLECTION_ARTICLE_ADDED_TRIGGER,
)
from app.automations.definitions.compiler import CompilationError, verify_compiled_plan
from app.automations.definitions.errors import AutomationDefinitionError
from app.automations.definitions.execution import require_exact_generation_prompts
from app.automations.definitions.models import Automation, AutomationNodeRun, AutomationRun, AutomationVersion
from app.automations.definitions.registry import COLLECTION_ARTICLE_ARTIFACT
from app.automations.definitions.schemas import WorkflowGraphV1
from app.automations.definitions.validation import validate_graph
from app.automations.telegram.route_policy import evaluate_content_filter
from app.db.models import ArticleCollection, ArticleCollectionItem, ContentItem
from app.generation.commands import GeneratePackRequest
from app.generation.editorial_service import EditorialService
from app.generation.errors import InvalidGenerationRequest
from app.jobs.errors import PermanentJobError
from app.jobs.models import AutomationControl, WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy
from app.stories.repository import StoryRepository


class CollectionArticleAddedJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_kind: Literal["collection_article_added"]
    automation_id: UUID
    automation_version_id: UUID
    trigger_node_id: str
    article_id: UUID
    collection_id: UUID
    source_event_id: str
    event_type: Literal["collection.article_added"]
    occurred_at: datetime
    actor_id: str | None = None


class CollectionArticleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str | None
    content: str | None
    url: str | None
    source_id: str | None
    published_at: str | None
    primary_media: dict[str, object] | None


class CollectionContextOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str


class CollectionArticleTriggerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["collection_article_added"]
    event_type: Literal["collection.article_added"]
    collection_id: str
    article_id: str
    source_event_id: str
    occurred_at: str
    actor_id: str | None


class CollectionArticleAddedOutput(BaseModel):
    """Stable payload carried by the article.collection_added artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    article: CollectionArticleOutput
    collection: CollectionContextOutput
    trigger: CollectionArticleTriggerOutput


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _primary_media(article: ContentItem) -> dict[str, object] | None:
    media = article.primary_media
    if media is None:
        return None
    return {
        "id": str(media.id),
        "url": media.normalized_url,
        "kind": media.kind,
        "mime_type": media.mime_type,
        "width": media.width,
        "height": media.height,
        "alt_text": media.alt_text,
    }


def _article_output(article: ContentItem) -> CollectionArticleOutput:
    return CollectionArticleOutput.model_validate({
        "id": str(article.id),
        "title": article.title,
        "content": article.content_text,
        "url": article.canonical_url,
        "source_id": str(article.primary_source_id) if article.primary_source_id is not None else None,
        "published_at": _iso(article.published_at),
        "primary_media": _primary_media(article),
    })


async def _load_run(
    session: AsyncSession,
    *,
    job: JobExecution,
    payload: CollectionArticleAddedJobPayload,
) -> tuple[AutomationRun, AutomationNodeRun]:
    if job.automation_run_id is None or job.automation_node_run_id is None:
        raise PermanentJobError(
            code="collection_trigger_link_missing",
            message="Collection trigger job is not linked to an Automation run",
        )
    run = await session.scalar(
        select(AutomationRun).where(AutomationRun.id == job.automation_run_id).with_for_update()
    )
    node = await session.scalar(
        select(AutomationNodeRun).where(AutomationNodeRun.id == job.automation_node_run_id).with_for_update()
    )
    if (
        run is None
        or node is None
        or node.automation_run_id != run.id
        or run.automation_id != payload.automation_id
        or run.automation_version_id != payload.automation_version_id
        or node.node_id != payload.trigger_node_id
    ):
        raise PermanentJobError(
            code="collection_trigger_link_invalid",
            message="Collection trigger job references an invalid Automation run",
        )
    return run, node


async def _finish_run(
    session: AsyncSession,
    *,
    job: JobExecution,
    run: AutomationRun,
    node: AutomationNodeRun,
    outcome: str,
    status: Literal["succeeded", "failed", "cancelled"],
    observed_at: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
    output: dict[str, object] | None = None,
) -> dict[str, object]:
    node.status = "succeeded" if status == "succeeded" else "failed" if status == "failed" else "skipped"
    node.started_at = node.started_at or observed_at
    node.finished_at = observed_at
    if output is not None:
        node.output_summary = output
    if error_code is not None:
        node.safe_error_code = error_code
        node.safe_error_message = error_message
    run.status = status
    run.current_node_id = None if status == "succeeded" else node.node_id
    run.safe_error_code = error_code
    run.safe_error_message = error_message
    run.finished_at = observed_at
    if status == "succeeded":
        event_type = "automation.run.completed"
    elif status == "cancelled":
        event_type = "automation.run.cancelled"
    else:
        event_type = "automation.run.failed"
    session.add(
        WorkflowEvent(
            workflow_job_id=job.id,
            event_type=event_type,
            actor="automation",
            event_data={
                "automation_run_id": str(run.id),
                "outcome": outcome,
                "error_code": error_code,
            },
        )
    )
    return {"outcome": outcome, "run_id": str(run.id), "article_id": str(run.trigger_metadata.get("article_id"))}


def _stage(plan: Any, node_type: str) -> Any | None:
    return next((item for item in plan.stages if item.node_type == node_type), None)


def _config_uuid(config: dict[str, object], field: str) -> UUID:
    value = config.get(field)
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field} is invalid") from None


def _mark_node(
    node: AutomationNodeRun,
    *,
    status: str,
    observed_at: datetime,
    input_summary: dict[str, object] | None = None,
    output_summary: dict[str, object] | None = None,
) -> None:
    node.status = status
    node.started_at = node.started_at or observed_at
    node.finished_at = observed_at
    if input_summary is not None:
        node.input_summary = input_summary
    if output_summary is not None:
        node.output_summary = output_summary


async def _start_collection_downstream(
    context: JobContext,
    *,
    job: JobExecution,
    run: AutomationRun,
    trigger_node: AutomationNodeRun,
    plan: Any,
    article: ContentItem,
    base_output: dict[str, object],
    observed_at: datetime,
    profile_resolver: Any | None,
) -> dict[str, object] | None:
    stages = list(plan.stages)
    entry_index = next(
        (index for index, stage in enumerate(stages) if stage.node_id == trigger_node.node_id),
        0,
    )
    downstream = stages[entry_index + 1 :]
    if not downstream:
        return None

    generation = next((stage for stage in downstream if stage.node_type == "generate_content_pack"), None)
    if generation is None:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=trigger_node,
            outcome="unsupported_downstream",
            status="failed",
            observed_at=observed_at,
            error_code="collection_article_downstream_unsupported",
            error_message="Collection article workflows require a content-package generation stage.",
            output=base_output,
        )

    generation_index = stages.index(generation)
    pre_generation = stages[entry_index + 1 : generation_index]
    supported_before_generation = {"filter_content", "research"}
    unsupported = [
        stage
        for stage in pre_generation
        if stage.node_type not in supported_before_generation
    ]
    if unsupported:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=trigger_node,
            outcome="unsupported_downstream",
            status="failed",
            observed_at=observed_at,
            error_code="collection_article_downstream_unsupported",
            error_message="Collection article output is not executable by one of the saved workflow stages.",
            output=base_output,
        )

    node_rows = {
        row.node_id: row
        for row in await context.session.scalars(
            select(AutomationNodeRun).where(AutomationNodeRun.automation_run_id == run.id)
        )
    }
    filter_output: dict[str, object] | None = None
    for stage in pre_generation:
        row = node_rows.get(stage.node_id)
        if row is None:
            return await _finish_run(
                context.session,
                job=job,
                run=run,
                node=trigger_node,
                outcome="invalid_workflow",
                status="failed",
                observed_at=observed_at,
                error_code="collection_article_node_run_missing",
                error_message="Collection article workflow state is incomplete.",
                output=base_output,
            )
        if stage.node_type != "filter_content":
            continue
        decision = evaluate_content_filter(
            " ".join(part for part in (article.title or "", article.content_text or "") if part),
            _primary_media(article) is not None,
            stage.config,
        )
        filter_output = {
            "artifact_type": COLLECTION_ARTICLE_ARTIFACT,
            "accepted": decision.accepted,
            "reason": decision.reason,
        }
        _mark_node(
            row,
            status="succeeded",
            observed_at=observed_at,
            input_summary=base_output,
            output_summary=filter_output,
        )
        if not decision.accepted:
            current_index = stages.index(stage)
            for pending_stage in stages[current_index + 1 :]:
                pending = node_rows.get(pending_stage.node_id)
                if pending is not None and pending.status == "pending":
                    _mark_node(
                        pending,
                        status="skipped",
                        observed_at=observed_at,
                        output_summary={"reason": "filtered", "filter": filter_output},
                    )
            filtered_output = {**base_output, "filter": filter_output}
            return {
                **await _finish_run(
                    context.session,
                    job=job,
                    run=run,
                    node=trigger_node,
                    outcome="filtered",
                    status="succeeded",
                    observed_at=observed_at,
                    output=filtered_output,
                ),
                "output": filtered_output,
            }

    grouping = await StoryRepository(context.session).group_content_items([article.id])
    if grouping.story is None:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=trigger_node,
            outcome="story_grouping_conflict",
            status="failed",
            observed_at=observed_at,
            error_code="collection_article_story_conflict",
            error_message="The collection article could not be materialized as one active story.",
            output=base_output,
        )

    research = _stage(plan, "research")
    try:
        await require_exact_generation_prompts(context.session, generate_config=generation.config)
        request = GeneratePackRequest(
            brand_profile_id=_config_uuid(generation.config, "editorial_profile_id"),
            platforms=list(generation.config.get("platforms") or ["telegram"]),  # type: ignore[arg-type]
            generation_provider_profile_id=_config_uuid(generation.config, "provider_profile_id"),
            research_mode=(str(research.config.get("mode")) if research is not None else "off"),  # type: ignore[arg-type]
            research_provider_profile_id=(
                _config_uuid(research.config, "provider_profile_id")
                if research is not None and research.config.get("provider_profile_id") is not None
                else None
            ),
        )
        accepted = await EditorialService(
            context.session,
            profile_resolver=profile_resolver,
        ).request_content_pack(grouping.story.id, request)
    except (AutomationDefinitionError, InvalidGenerationRequest, TypeError, ValueError):
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=trigger_node,
            outcome="generation_unavailable",
            status="failed",
            observed_at=observed_at,
            error_code="collection_article_generation_unavailable",
            error_message="Collection article generation resources are unavailable.",
            output=base_output,
        )

    child = await context.session.get(WorkflowJob, accepted.job_id)
    if child is None:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=trigger_node,
            outcome="generation_unavailable",
            status="failed",
            observed_at=observed_at,
            error_code="collection_article_generation_job_missing",
            error_message="Collection article generation job was not created.",
            output=base_output,
        )
    if child.automation_run_id is not None and child.automation_run_id != run.id:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=trigger_node,
            outcome="generation_conflict",
            status="failed",
            observed_at=observed_at,
            error_code="collection_article_generation_owned",
            error_message="Collection article generation job is already owned by another workflow run.",
            output=base_output,
        )

    node_rows = {
        row.node_id: row
        for row in await context.session.scalars(
            select(AutomationNodeRun).where(AutomationNodeRun.automation_run_id == run.id)
        )
    }
    target_stage = research if research is not None and child.job_type == "research_story" else generation
    target_node = node_rows.get(target_stage.node_id)
    if target_node is None:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=trigger_node,
            outcome="invalid_workflow",
            status="failed",
            observed_at=observed_at,
            error_code="collection_article_node_run_missing",
            error_message="Collection article workflow state is incomplete.",
            output=base_output,
        )

    if research is not None and target_stage.node_id != research.node_id:
        research_node = node_rows.get(research.node_id)
        if research_node is not None and research_node.status == "pending":
            _mark_node(
                research_node,
                status="skipped",
                observed_at=observed_at,
                output_summary={"reason": "research_not_required"},
            )
    _mark_node(
        trigger_node,
        status="succeeded",
        observed_at=observed_at,
        output_summary=base_output,
    )
    target_node.status = "queued"
    target_node.workflow_job_id = child.id
    child.automation_run_id = run.id
    child.automation_node_run_id = target_node.id
    run.status = "running"
    run.current_node_id = target_node.node_id
    run.finished_at = None
    return {
        "outcome": "started",
        "run_id": str(run.id),
        "article_id": str(article.id),
        "collection_id": str(base_output["collection"]["id"]),  # type: ignore[index]
        "story_id": str(grouping.story.id),
        "output": base_output,
        "continuation_job_id": str(child.id),
        "continuation_node_id": target_node.node_id,
    }


async def handle_collection_article_added(
    job: JobExecution,
    context: JobContext,
    *,
    profile_resolver: Any | None = None,
) -> dict[str, Any]:
    try:
        payload = CollectionArticleAddedJobPayload.model_validate(job_payload_copy(job))
    except ValueError as exc:
        raise PermanentJobError(
            code="collection_trigger_payload_invalid",
            message="Collection article trigger payload is invalid",
        ) from exc

    run, node = await _load_run(context.session, job=job, payload=payload)
    if run.status in {"succeeded", "failed", "cancelled", "warning"}:
        return {
            "outcome": "replayed",
            "run_id": str(run.id),
            "article_id": str(payload.article_id),
        }
    if node.status == "succeeded":
        continuation_node = (
            await context.session.scalar(
                select(AutomationNodeRun).where(
                    AutomationNodeRun.automation_run_id == run.id,
                    AutomationNodeRun.node_id == run.current_node_id,
                )
            )
            if run.current_node_id is not None
            else None
        )
        continuation_job = (
            await context.session.get(WorkflowJob, continuation_node.workflow_job_id)
            if continuation_node is not None and continuation_node.workflow_job_id is not None
            else None
        )
        replay = {
            "outcome": "replayed",
            "run_id": str(run.id),
            "article_id": str(payload.article_id),
        }
        if continuation_job is not None and continuation_node is not None:
            replay.update(
                continuation_job_id=str(continuation_job.id),
                continuation_node_id=continuation_node.node_id,
            )
        return replay

    observed_at = datetime.now(UTC)
    automation = await context.session.scalar(
        select(Automation).where(Automation.id == payload.automation_id).with_for_update()
    )
    control = await context.session.get(AutomationControl, "global")
    if automation is None or automation.lifecycle != "active" or automation.archived_at is not None:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=node,
            outcome="inactive",
            status="cancelled",
            observed_at=observed_at,
            error_code="automation_not_active",
            error_message="Automation is no longer active",
        )
    if control is not None and control.global_pause:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=node,
            outcome="paused",
            status="cancelled",
            observed_at=observed_at,
            error_code="automation_globally_paused",
            error_message="Automation execution is globally paused",
        )
    if automation.active_version_id != payload.automation_version_id:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=node,
            outcome="stale_version",
            status="cancelled",
            observed_at=observed_at,
            error_code="automation_version_inactive",
            error_message="Automation version is no longer active",
        )

    version = await context.session.get(AutomationVersion, payload.automation_version_id)
    collection = await context.session.get(ArticleCollection, payload.collection_id)
    membership = await context.session.scalar(
        select(ArticleCollectionItem.saved_at).where(
            ArticleCollectionItem.collection_id == payload.collection_id,
            ArticleCollectionItem.content_item_id == payload.article_id,
        )
    )
    article = await context.session.scalar(
        select(ContentItem)
        .options(selectinload(ContentItem.primary_media))
        .where(ContentItem.id == payload.article_id)
    )
    if version is None or collection is None or membership is None or article is None:
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=node,
            outcome="source_unavailable",
            status="cancelled",
            observed_at=observed_at,
            error_code="collection_article_unavailable",
            error_message="The saved article or Feed collection is no longer available",
        )

    try:
        graph = WorkflowGraphV1.model_validate(version.graph)
        validation = validate_graph(graph)
        plan = verify_compiled_plan(graph, version.compiled_plan)
    except (CompilationError, TypeError, ValueError):
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=node,
            outcome="invalid_workflow",
            status="failed",
            observed_at=observed_at,
            error_code="automation_version_invalid",
            error_message="Automation version is no longer executable",
        )
    entry = next((item for item in graph.nodes if item.id == graph.entry_node_id), None)
    if (
        not validation.valid
        or entry is None
        or entry.id != payload.trigger_node_id
        or entry.type != COLLECTION_ARTICLE_ADDED_TRIGGER
        or str(entry.config.get("collection_id")) != str(payload.collection_id)
        or plan.entry_node_id != payload.trigger_node_id
        or plan.trigger_kind != COLLECTION_ARTICLE_ADDED_TRIGGER
    ):
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=node,
            outcome="invalid_workflow",
            status="failed",
            observed_at=observed_at,
            error_code="automation_trigger_invalid",
            error_message="Automation trigger no longer matches its saved collection",
        )

    output_model = CollectionArticleAddedOutput.model_validate(
        {
            "article": _article_output(article).model_dump(mode="json"),
            "collection": {
                "id": str(collection.id),
                "name": collection.name,
            },
            "trigger": {
                "type": "collection_article_added",
                "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
                "collection_id": str(payload.collection_id),
                "article_id": str(payload.article_id),
                "source_event_id": payload.source_event_id,
                "occurred_at": _utc(payload.occurred_at).isoformat(),
                "actor_id": payload.actor_id,
            },
        }
    )
    output = output_model.model_dump(mode="json")
    node.input_summary = {
        "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
        "article_id": str(payload.article_id),
        "collection_id": str(payload.collection_id),
        "source_event_id": payload.source_event_id,
    }
    downstream = await _start_collection_downstream(
        context,
        job=job,
        run=run,
        trigger_node=node,
        plan=plan,
        article=article,
        base_output=output,
        observed_at=observed_at,
        profile_resolver=profile_resolver,
    )
    if downstream is not None:
        return downstream
    result = await _finish_run(
        context.session,
        job=job,
        run=run,
        node=node,
        outcome="started",
        status="succeeded",
        observed_at=observed_at,
        output=output,
    )
    return {**result, "output": output}


def build_collection_article_added_handler(profile_resolver: Any | None = None) -> JobHandler:
    if profile_resolver is None:
        return handle_collection_article_added

    async def handler(job: JobExecution, context: JobContext) -> dict[str, Any]:
        return await handle_collection_article_added(job, context, profile_resolver=profile_resolver)

    handler.__annotations__ = {
        "job": JobExecution,
        "context": JobContext,
        "return": dict[str, Any],
    }
    return handler


__all__ = [
    "CollectionArticleAddedOutput",
    "CollectionArticleAddedJobPayload",
    "CollectionArticleOutput",
    "CollectionArticleTriggerOutput",
    "CollectionContextOutput",
    "build_collection_article_added_handler",
    "handle_collection_article_added",
]
