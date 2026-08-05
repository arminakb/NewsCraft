from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.automations.definitions.compiler import CompilationError, verify_compiled_plan
from app.automations.definitions.models import Automation, AutomationNodeRun, AutomationRun, AutomationVersion
from app.automations.definitions.schemas import WorkflowGraphV1
from app.automations.definitions.source_events import SOURCE_ITEM_CREATED_EVENT, SOURCE_ITEM_CREATED_TRIGGER
from app.automations.definitions.validation import validate_graph
from app.db.models import ContentItem, Source, SourceItem
from app.jobs.errors import PermanentJobError
from app.jobs.models import AutomationControl, WorkflowEvent
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy


class NewSourceItemJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trigger_kind: Literal["new_source_item"]
    automation_id: UUID
    automation_version_id: UUID
    trigger_node_id: str
    source_item_id: UUID
    source_id: UUID
    platform: str
    content_item_id: UUID | None = None
    ingestion_run_id: UUID
    source_event_id: str
    event_type: Literal["source_item.created"]
    occurred_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _primary_media(item: ContentItem) -> dict[str, object] | None:
    media = item.primary_media
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


def _source_item_output(source: Source, source_item: SourceItem, content_item: ContentItem) -> dict[str, object]:
    authors = content_item.authors if isinstance(content_item.authors, list) else []
    if not authors and source_item.author_raw:
        authors = [source_item.author_raw]
    return {
        "id": str(source_item.id),
        "source_id": str(source.id),
        "platform": source.platform,
        "title": source_item.title_raw or content_item.title or "",
        "content": source_item.content_text_raw or content_item.content_text or "",
        "url": source_item.source_url or source_item.source_url_norm or content_item.canonical_url,
        "authors": authors,
        "published_at": _iso(content_item.published_at) or source_item.published_raw,
        "primary_media": _primary_media(content_item),
    }


def _content_item_output(content_item: ContentItem) -> dict[str, object]:
    return {
        "id": str(content_item.id),
        "content_type": content_item.content_type,
        "score": content_item.score,
        "rewrite_bucket": content_item.rewrite_bucket,
    }


async def _load_run(
    session: AsyncSession,
    *,
    job: JobExecution,
    payload: NewSourceItemJobPayload,
) -> tuple[AutomationRun, AutomationNodeRun]:
    if job.automation_run_id is None or job.automation_node_run_id is None:
        raise PermanentJobError(
            code="source_item_trigger_link_missing",
            message="New Source Item job is not linked to an Automation run",
        )
    run = await session.scalar(select(AutomationRun).where(AutomationRun.id == job.automation_run_id).with_for_update())
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
            code="source_item_trigger_link_invalid",
            message="New Source Item job references an invalid Automation run",
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
    event_type = (
        "automation.run.completed"
        if status == "succeeded"
        else "automation.run.cancelled"
        if status == "cancelled"
        else "automation.run.failed"
    )
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
    return {
        "outcome": outcome,
        "run_id": str(run.id),
        "source_item_id": str(run.trigger_metadata.get("source_item_id")),
    }


async def handle_new_source_item(job: JobExecution, context: JobContext) -> dict[str, Any]:
    try:
        payload = NewSourceItemJobPayload.model_validate(job_payload_copy(job))
    except ValueError as exc:
        raise PermanentJobError(
            code="source_item_trigger_payload_invalid",
            message="New Source Item trigger payload is invalid",
        ) from exc

    run, node = await _load_run(context.session, job=job, payload=payload)
    if run.status in {"succeeded", "failed", "cancelled", "warning"} or node.status == "succeeded":
        return {"outcome": "replayed", "run_id": str(run.id), "source_item_id": str(payload.source_item_id)}

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
    source = await context.session.get(Source, payload.source_id)
    source_item = await context.session.scalar(
        select(SourceItem).where(
            SourceItem.id == payload.source_item_id,
            SourceItem.source_id == payload.source_id,
        )
    )
    content_item_id = source_item.content_item_id if source_item is not None else None
    content_item = (
        await context.session.scalar(
            select(ContentItem)
            .options(selectinload(ContentItem.primary_media))
            .where(ContentItem.id == content_item_id)
        )
        if content_item_id is not None
        else None
    )
    content_link_mismatch = payload.content_item_id is not None and (
        source_item is None or source_item.content_item_id != payload.content_item_id
    )
    if (
        version is None
        or source is None
        or source.deleted_at is not None
        or not source.active
        or source_item is None
        or content_item is None
        or content_link_mismatch
    ):
        return await _finish_run(
            context.session,
            job=job,
            run=run,
            node=node,
            outcome="source_unavailable",
            status="cancelled",
            observed_at=observed_at,
            error_code="source_item_unavailable",
            error_message="The source item or normalized content is no longer available",
        )
    if source_item is None or content_item is None or source is None or version is None:  # pragma: no cover
        raise RuntimeError("source trigger availability narrowing failed")

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
    configured_ids = entry.config.get("source_ids") if entry is not None else None
    if (
        not validation.valid
        or entry is None
        or entry.id != payload.trigger_node_id
        or entry.type != SOURCE_ITEM_CREATED_TRIGGER
        or not isinstance(configured_ids, list)
        or str(payload.source_id) not in {str(item) for item in configured_ids}
        or plan.entry_node_id != payload.trigger_node_id
        or plan.trigger_kind != SOURCE_ITEM_CREATED_TRIGGER
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
            error_message="Automation trigger no longer matches its saved sources",
        )

    trigger = {
        "type": SOURCE_ITEM_CREATED_TRIGGER,
        "source_item_id": str(payload.source_item_id),
        "source_id": str(payload.source_id),
        "ingestion_run_id": str(payload.ingestion_run_id),
        "occurred_at": _utc(payload.occurred_at).isoformat(),
    }
    output = {
        "source_item": _source_item_output(source, source_item, content_item),
        "content_item": _content_item_output(content_item),
        "trigger": trigger,
    }
    node.input_summary = {
        "event_type": SOURCE_ITEM_CREATED_EVENT,
        "source_item_id": str(payload.source_item_id),
        "source_id": str(payload.source_id),
        "content_item_id": str(content_item.id),
        "ingestion_run_id": str(payload.ingestion_run_id),
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


def build_new_source_item_handler() -> JobHandler:
    return handle_new_source_item


__all__ = [
    "NewSourceItemJobPayload",
    "build_new_source_item_handler",
    "handle_new_source_item",
]
