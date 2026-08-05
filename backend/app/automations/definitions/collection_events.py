from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.compiler import verify_compiled_plan
from app.automations.definitions.models import Automation, AutomationNodeRun, AutomationRun, AutomationVersion
from app.automations.definitions.schemas import WorkflowGraphV1
from app.automations.definitions.validation import validate_graph
from app.jobs.models import AutomationControl, WorkflowEvent
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin

COLLECTION_ARTICLE_ADDED_EVENT = "collection.article_added"
COLLECTION_ARTICLE_ADDED_TRIGGER = "collection_article_added"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def collection_article_event_id(*, collection_id: UUID, article_id: UUID) -> str:
    return f"{COLLECTION_ARTICLE_ADDED_EVENT}:{collection_id}:{article_id}"


def collection_article_run_idempotency_key(
    *,
    automation_id: UUID,
    version_id: UUID,
    trigger_node_id: str,
    article_id: UUID,
    collection_id: UUID,
    source_event_id: str,
) -> str:
    return (
        f"automation-run:{automation_id}:version:{version_id}:trigger:{trigger_node_id}:"
        f"article:{article_id}:collection:{collection_id}:event:{source_event_id}"
    )


def _request_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def enqueue_collection_article_added(
    session: AsyncSession,
    *,
    article_id: UUID,
    collection_id: UUID,
    added_at: datetime,
    actor_id: str,
) -> list[UUID]:
    """Persist one collection event and enqueue one durable root job per match.

    Membership insertion is the event boundary. Callers invoke this only after
    PostgreSQL reports a newly inserted ArticleCollectionItem, so repeated PUTs
    cannot emit another event or run.
    """

    source_event_id = collection_article_event_id(collection_id=collection_id, article_id=article_id)
    normalized_actor = actor_id.strip()[:255] or "operator"
    existing_event = await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.event_type == COLLECTION_ARTICLE_ADDED_EVENT,
            WorkflowEvent.event_data["source_event_id"].astext == source_event_id,
        )
        .limit(1)
    )
    if existing_event is None:
        session.add(
            WorkflowEvent(
                id=uuid4(),
                workflow_job_id=None,
                event_type=COLLECTION_ARTICLE_ADDED_EVENT,
                actor=normalized_actor,
                event_data={
                    "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
                    "source_event_id": source_event_id,
                    "article_id": str(article_id),
                    "collection_id": str(collection_id),
                    "added_at": _utc(added_at).isoformat(),
                    "actor_id": normalized_actor,
                },
            )
        )

    control = await session.get(AutomationControl, "global")
    if control is not None and control.global_pause:
        return []

    active_versions = list(
        (
            await session.execute(
                select(Automation, AutomationVersion)
                .join(AutomationVersion, AutomationVersion.id == Automation.active_version_id)
                .where(
                    Automation.lifecycle == "active",
                    Automation.archived_at.is_(None),
                )
            )
        ).all()
    )
    created_run_ids: list[UUID] = []
    now = datetime.now(UTC)
    for automation, version in active_versions:
        try:
            graph = WorkflowGraphV1.model_validate(version.graph)
            validation = validate_graph(graph)
            if not validation.valid:
                continue
            plan = verify_compiled_plan(graph, version.compiled_plan)
        except (TypeError, ValueError):
            continue
        entry = next((node for node in graph.nodes if node.id == graph.entry_node_id), None)
        if entry is None or entry.type != COLLECTION_ARTICLE_ADDED_TRIGGER:
            continue
        if str(entry.config.get("collection_id")) != str(collection_id):
            continue
        run_key = collection_article_run_idempotency_key(
            automation_id=automation.id,
            version_id=version.id,
            trigger_node_id=entry.id,
            article_id=article_id,
            collection_id=collection_id,
            source_event_id=source_event_id,
        )
        existing = await session.scalar(select(AutomationRun).where(AutomationRun.idempotency_key == run_key))
        if existing is not None:
            created_run_ids.append(existing.id)
            continue

        trigger_metadata = {
            "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
            "source_event_id": source_event_id,
            "article_id": str(article_id),
            "collection_id": str(collection_id),
            "added_at": _utc(added_at).isoformat(),
            "actor_id": normalized_actor,
            "workflow_version": version.version,
            "trigger_node_id": entry.id,
        }
        run = AutomationRun(
            id=uuid4(),
            automation_id=automation.id,
            automation_version_id=version.id,
            trigger_kind=COLLECTION_ARTICLE_ADDED_TRIGGER,
            trigger_metadata=trigger_metadata,
            dry_run=bool(control.dry_run) if control is not None else False,
            status="queued",
            current_node_id=entry.id,
            resource_snapshot={
                "automation_version": version.version,
                "graph_hash": version.graph_hash,
                "compiler_version": plan.compiler_version,
                "plan_hash": plan.plan_hash,
                "required_resources": list(plan.required_resources),
                "node_ids_by_type": _node_ids_by_type(plan),
                "article_id": str(article_id),
                "collection_id": str(collection_id),
                "source_event_id": source_event_id,
            },
            idempotency_key=run_key,
            request_hash=_request_hash(trigger_metadata),
            started_at=now,
        )
        session.add(run)
        await session.flush()

        node_rows: dict[str, AutomationNodeRun] = {}
        for stage in plan.stages:
            row = AutomationNodeRun(
                id=uuid4(),
                automation_run_id=run.id,
                node_id=stage.node_id,
                status="pending",
                input_summary={
                    "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
                    "article_id": str(article_id),
                    "collection_id": str(collection_id),
                }
                if stage.node_id == entry.id
                else {},
            )
            session.add(row)
            node_rows[stage.node_id] = row
        await session.flush()

        queued = await JobRepository(session).enqueue_job(
            job_type="automation.run.start",
            payload={
                "trigger_kind": COLLECTION_ARTICLE_ADDED_TRIGGER,
                "automation_id": str(automation.id),
                "automation_version_id": str(version.id),
                "trigger_node_id": entry.id,
                "article_id": str(article_id),
                "collection_id": str(collection_id),
                "source_event_id": source_event_id,
                "event_type": COLLECTION_ARTICLE_ADDED_EVENT,
                "occurred_at": _utc(added_at).isoformat(),
                "actor_id": normalized_actor,
            },
            idempotency_key=f"{run_key}:job",
            origin=JobOrigin.AUTOMATION,
            automation_run_id=run.id,
            automation_node_run_id=node_rows[entry.id].id,
        )
        run.root_workflow_job_id = queued.job.id
        node_rows[entry.id].workflow_job_id = queued.job.id
        session.add(
            WorkflowEvent(
                workflow_job_id=queued.job.id,
                event_type="automation.run.started",
                actor=normalized_actor,
                event_data={
                    "automation_id": str(automation.id),
                    "automation_run_id": str(run.id),
                    "automation_version": version.version,
                    "trigger_node_id": entry.id,
                    "article_id": str(article_id),
                    "collection_id": str(collection_id),
                    "source_event_id": source_event_id,
                },
            )
        )
        created_run_ids.append(run.id)

    return created_run_ids


def _node_ids_by_type(plan: Any) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for stage in plan.stages:
        output.setdefault(stage.node_type, []).append(stage.node_id)
    return output


__all__ = [
    "COLLECTION_ARTICLE_ADDED_EVENT",
    "COLLECTION_ARTICLE_ADDED_TRIGGER",
    "collection_article_event_id",
    "collection_article_run_idempotency_key",
    "enqueue_collection_article_added",
]
