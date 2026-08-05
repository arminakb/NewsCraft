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
from app.automations.definitions.models import Automation, AutomationNodeRun, AutomationRun, AutomationVersion
from app.automations.definitions.schemas import WorkflowGraphV1
from app.automations.definitions.validation import validate_graph
from app.db.models import ArticleCollection, ArticleCollectionItem, ContentItem
from app.jobs.errors import PermanentJobError
from app.jobs.models import AutomationControl, WorkflowEvent
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy


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


def _article_output(article: ContentItem) -> dict[str, object]:
    return {
        "id": str(article.id),
        "title": article.title,
        "content": article.content_text,
        "url": article.canonical_url,
        "source_id": str(article.primary_source_id) if article.primary_source_id is not None else None,
        "published_at": _iso(article.published_at),
        "primary_media": _primary_media(article),
    }


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


async def handle_collection_article_added(job: JobExecution, context: JobContext) -> dict[str, Any]:
    try:
        payload = CollectionArticleAddedJobPayload.model_validate(job_payload_copy(job))
    except ValueError as exc:
        raise PermanentJobError(
            code="collection_trigger_payload_invalid",
            message="Collection article trigger payload is invalid",
        ) from exc

    run, node = await _load_run(context.session, job=job, payload=payload)
    if run.status in {"succeeded", "failed", "cancelled", "warning"} or node.status == "succeeded":
        return {
            "outcome": "replayed",
            "run_id": str(run.id),
            "article_id": str(payload.article_id),
        }

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

    trigger = {
        "type": "collection_article_added",
        "collection_id": str(payload.collection_id),
        "article_id": str(payload.article_id),
        "occurred_at": _utc(payload.occurred_at).isoformat(),
    }
    output = {"article": _article_output(article), "trigger": trigger}
    node.input_summary = {
        "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
        "article_id": str(payload.article_id),
        "collection_id": str(payload.collection_id),
        "source_event_id": payload.source_event_id,
    }
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


def build_collection_article_added_handler() -> JobHandler:
    return handle_collection_article_added


__all__ = [
    "CollectionArticleAddedJobPayload",
    "build_collection_article_added_handler",
    "handle_collection_article_added",
]
