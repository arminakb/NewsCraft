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
from app.automations.definitions.trigger_runtime import utc
from app.automations.definitions.validation import validate_graph
from app.db.models import Source
from app.jobs.models import AutomationControl, WorkflowEvent
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin

SOURCE_ITEM_CREATED_EVENT = "source_item.created"
SOURCE_ITEM_CREATED_TRIGGER = "new_source_item"


def source_item_event_id(source_item_id: UUID) -> str:
    return f"{SOURCE_ITEM_CREATED_EVENT}:{source_item_id}"


def source_item_run_idempotency_key(
    *,
    automation_id: UUID,
    version_id: UUID,
    trigger_node_id: str,
    source_item_id: UUID,
) -> str:
    return (
        f"automation-run:{automation_id}:version:{version_id}:trigger:{trigger_node_id}:"
        f"source-item:{source_item_id}"
    )


def _request_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


async def enqueue_source_item_created(
    session: AsyncSession,
    *,
    source_item_id: UUID,
    source_id: UUID,
    platform: str,
    content_item_id: UUID | None,
    ingestion_run_id: UUID,
    occurred_at: datetime,
) -> list[UUID]:
    """Persist one source-item event and enqueue immutable active-version runs.

    The caller invokes this inside the same transaction that inserted the
    SourceItem and linked ContentItem. Existing events are a hard no-op so a
    replay cannot backfill workflows activated after the original item.
    """

    source_event_id = source_item_event_id(source_item_id)
    existing_event = await session.scalar(
        select(WorkflowEvent)
        .where(
            WorkflowEvent.event_type == SOURCE_ITEM_CREATED_EVENT,
            WorkflowEvent.event_data["source_event_id"].astext == source_event_id,
        )
        .limit(1)
    )
    if existing_event is not None:
        return []

    occurred = utc(occurred_at)
    event_data: dict[str, object] = {
        "event_type": SOURCE_ITEM_CREATED_EVENT,
        "source_event_id": source_event_id,
        "source_item_id": str(source_item_id),
        "source_id": str(source_id),
        "platform": platform,
        "content_item_id": str(content_item_id) if content_item_id is not None else None,
        "ingestion_run_id": str(ingestion_run_id),
        "occurred_at": occurred.isoformat(),
    }
    session.add(
        WorkflowEvent(
            id=uuid4(),
            workflow_job_id=None,
            event_type=SOURCE_ITEM_CREATED_EVENT,
            actor="ingestion",
            event_data=event_data,
        )
    )

    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None or not source.active:
        return []

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
        if entry is None or entry.type != SOURCE_ITEM_CREATED_TRIGGER:
            continue
        configured_ids = entry.config.get("source_ids")
        if not isinstance(configured_ids, list) or str(source_id) not in {str(item) for item in configured_ids}:
            continue

        run_key = source_item_run_idempotency_key(
            automation_id=automation.id,
            version_id=version.id,
            trigger_node_id=entry.id,
            source_item_id=source_item_id,
        )
        existing = await session.scalar(select(AutomationRun).where(AutomationRun.idempotency_key == run_key))
        if existing is not None:
            created_run_ids.append(existing.id)
            continue

        trigger_metadata = {
            **event_data,
            "workflow_version": version.version,
            "trigger_node_id": entry.id,
        }
        run = AutomationRun(
            id=uuid4(),
            automation_id=automation.id,
            automation_version_id=version.id,
            trigger_kind=SOURCE_ITEM_CREATED_TRIGGER,
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
                "node_types_by_id": {stage.node_id: stage.node_type for stage in plan.stages},
                "node_order": [stage.node_id for stage in plan.stages],
                "source_item_id": str(source_item_id),
                "source_id": str(source_id),
                "content_item_id": str(content_item_id) if content_item_id is not None else None,
                "ingestion_run_id": str(ingestion_run_id),
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
                input_summary=(
                    {
                        "event_type": SOURCE_ITEM_CREATED_EVENT,
                        "source_item_id": str(source_item_id),
                        "source_id": str(source_id),
                        "content_item_id": str(content_item_id) if content_item_id is not None else None,
                        "ingestion_run_id": str(ingestion_run_id),
                    }
                    if stage.node_id == entry.id
                    else {}
                ),
            )
            session.add(row)
            node_rows[stage.node_id] = row
        await session.flush()

        queued = await JobRepository(session).enqueue_job(
            job_type="automation.run.start",
            payload={
                "trigger_kind": SOURCE_ITEM_CREATED_TRIGGER,
                "automation_id": str(automation.id),
                "automation_version_id": str(version.id),
                "trigger_node_id": entry.id,
                "source_item_id": str(source_item_id),
                "source_id": str(source_id),
                "platform": platform,
                "content_item_id": str(content_item_id) if content_item_id is not None else None,
                "ingestion_run_id": str(ingestion_run_id),
                "source_event_id": source_event_id,
                "event_type": SOURCE_ITEM_CREATED_EVENT,
                "occurred_at": occurred.isoformat(),
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
                actor="ingestion",
                event_data={
                    "automation_id": str(automation.id),
                    "automation_run_id": str(run.id),
                    "automation_version": version.version,
                    "trigger_node_id": entry.id,
                    "source_item_id": str(source_item_id),
                    "source_id": str(source_id),
                    "content_item_id": str(content_item_id) if content_item_id is not None else None,
                    "ingestion_run_id": str(ingestion_run_id),
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
    "SOURCE_ITEM_CREATED_EVENT",
    "SOURCE_ITEM_CREATED_TRIGGER",
    "enqueue_source_item_created",
    "source_item_event_id",
    "source_item_run_idempotency_key",
]
