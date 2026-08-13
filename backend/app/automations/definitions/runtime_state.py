from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.artifacts import (
    artifact_for_result,
    normalize_artifact,
    review_artifact,
    summary_with_artifact,
)
from app.automations.definitions.models import AutomationNodeRun, AutomationRun
from app.automations.definitions.schemas import WorkflowArtifact
from app.core.redaction import redact_secrets
from app.jobs.models import WorkflowEvent, WorkflowJob


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value is not None else None
    except (ValueError, TypeError):
        return None


_JOB_NODE_TYPES: dict[str, str] = {
    "research_story": "research",
    "content_pack.generate": "generate_content_pack",
    "content_pack.generate_telegram": "generate_content_pack",
    "build_export": "manual_package",
    "telegram.publish": "telegram_publish",
    "telegram.route.process": "filter_content",
    "telegram.route.dry_run": "filter_content",
}
_PRESERVING_NODE_TYPES = frozenset({"filter_content", "validate", "human_review", "save_drafts", "manual_package"})


def _node_type(run: AutomationRun, node: AutomationNodeRun, job: WorkflowJob) -> str:
    snapshot = run.resource_snapshot or {}
    by_id = snapshot.get("node_types_by_id")
    if isinstance(by_id, dict) and isinstance(by_id.get(node.node_id), str):
        return str(by_id[node.node_id])
    return _JOB_NODE_TYPES.get(job.job_type, "")


def _next_node_type(run: AutomationRun, node: AutomationNodeRun) -> str | None:
    order = (run.resource_snapshot or {}).get("node_order")
    node_types = (run.resource_snapshot or {}).get("node_types_by_id")
    if not isinstance(order, list) or not isinstance(node_types, dict):
        return None
    try:
        index = order.index(node.node_id)
    except ValueError:
        return None
    if index + 1 >= len(order):
        return None
    next_node_id = order[index + 1]
    next_type = node_types.get(next_node_id)
    return str(next_type) if isinstance(next_type, str) else None


def _project_artifact(
    run: AutomationRun,
    node: AutomationNodeRun,
    job: WorkflowJob,
    result: dict[str, object],
) -> tuple[dict[str, object], WorkflowArtifact[object] | None]:
    node_type = _node_type(run, node, job)
    existing = normalize_artifact(node.output_summary, source_node_id=node.node_id, run_id=str(run.id))
    artifact = existing
    if artifact is None and node_type in _PRESERVING_NODE_TYPES:
        artifact = normalize_artifact(
            (run.resource_snapshot or {}).get("current_artifact"),
            source_node_id=node.node_id,
            workflow_id=str(getattr(run, "automation_id", "")) or None,
            workflow_version_id=str(getattr(run, "automation_version_id", "")) or None,
            run_id=str(run.id),
        )
    if artifact is None:
        artifact = artifact_for_result(
            result,
            node_type=node_type,
            source_node_id=node.node_id,
            workflow_id=str(getattr(run, "automation_id", "")) or None,
            workflow_version_id=str(getattr(run, "automation_version_id", "")) or None,
            run_id=str(run.id),
        )
    if artifact is None:
        return result, None
    result["artifact"] = artifact.model_dump(mode="json")
    return summary_with_artifact(result, artifact), artifact


async def _node_by_type(session: AsyncSession, run: AutomationRun, node_type: str) -> AutomationNodeRun | None:
    node_ids = (run.resource_snapshot or {}).get("node_ids_by_type", {}).get(node_type, [])
    if not isinstance(node_ids, list) or not node_ids:
        return None
    return await session.scalar(
        select(AutomationNodeRun).where(
            AutomationNodeRun.automation_run_id == run.id,
            AutomationNodeRun.node_id == str(node_ids[0]),
        )
    )


async def sync_automation_job_succeeded(
    session: AsyncSession,
    *,
    job: WorkflowJob,
    result: dict[str, object],
    observed_at: datetime,
) -> None:
    if job.automation_run_id is None or job.automation_node_run_id is None:
        return
    run = await session.scalar(select(AutomationRun).where(AutomationRun.id == job.automation_run_id).with_for_update())
    node = await session.scalar(
        select(AutomationNodeRun)
        .where(AutomationNodeRun.id == job.automation_node_run_id)
        .with_for_update()
    )
    if run is None or node is None or node.automation_run_id != run.id:
        return
    projected_result, artifact = _project_artifact(run, node, job, result)
    if run.status in {"succeeded", "failed", "cancelled", "warning"} and node.status in {
        "succeeded",
        "failed",
        "skipped",
    }:
        # Some trigger handlers finish their run atomically while producing the
        # canonical trigger output. The projection wrapper must not append a
        # second completion event or overwrite that terminal state.
        if artifact is not None:
            projected_safe = redact_secrets(projected_result)
            node.output_summary = projected_safe if isinstance(projected_safe, dict) else {}
            snapshot = dict(run.resource_snapshot or {})
            snapshot["current_artifact"] = artifact.model_dump(mode="json")
            run.resource_snapshot = snapshot
        return
    safe_result = redact_secrets(projected_result)
    node.output_summary = safe_result if isinstance(safe_result, dict) else {}
    if artifact is not None:
        snapshot = dict(run.resource_snapshot or {})
        snapshot["current_artifact"] = artifact.model_dump(mode="json")
        run.resource_snapshot = snapshot
    node.started_at = node.started_at or job.started_at or observed_at
    continuation_id = _uuid(projected_result.get("continuation_job_id"))
    if continuation_id is not None:
        continuation = await session.get(WorkflowJob, continuation_id)
        if continuation is not None:
            if _next_node_type(run, node) == "human_review" and artifact is not None:
                review = await _node_by_type(session, run, "human_review")
                if review is not None:
                    node.status = "succeeded"
                    node.finished_at = observed_at
                    review.input_summary = summary_with_artifact(projected_result, artifact)
                    review.output_summary = summary_with_artifact(
                        {
                            "status": "waiting_for_review",
                            "continuation_job_id": str(continuation.id),
                        },
                        artifact,
                    )
                    review.status = "waiting_for_review"
                    review.started_at = observed_at
                    continuation.status = "cancelled"
                    continuation.finished_at = observed_at
                    run.status = "waiting_for_review"
                    run.current_node_id = review.node_id
                    session.add(
                        WorkflowEvent(
                            workflow_job_id=job.id,
                            event_type="automation.run.waiting_for_review",
                            actor="automation",
                            event_data={
                                "automation_run_id": str(run.id),
                                "review_node_id": review.node_id,
                                "artifact_kind": artifact.kind,
                            },
                        )
                    )
                    return
            target = node
            continuation_node_id = projected_result.get("continuation_node_id")
            if isinstance(continuation_node_id, str) and continuation_node_id:
                continuation_target = await session.scalar(
                    select(AutomationNodeRun).where(
                        AutomationNodeRun.automation_run_id == run.id,
                        AutomationNodeRun.node_id == continuation_node_id,
                    )
                )
                if continuation_target is None:
                    return
                target = continuation_target
            elif job.job_type == "research_story":
                node.status = "succeeded"
                node.finished_at = observed_at
                generation = await _node_by_type(session, run, "generate_content_pack")
                if generation is not None:
                    target = generation
            continuation.automation_run_id = run.id
            continuation.automation_node_run_id = target.id
            target.workflow_job_id = continuation.id
            target.status = "queued"
            run.status = "running"
            run.current_node_id = target.node_id
            return

    node.status = "succeeded"
    node.finished_at = observed_at
    dispatch_id = _uuid(projected_result.get("dispatch_id"))
    generation_id = _uuid(projected_result.get("generation_run_id"))
    revision_id = _uuid(projected_result.get("revision_id"))
    publication_id = _uuid(projected_result.get("publication_id"))
    if dispatch_id is not None:
        node.automation_dispatch_id = dispatch_id
    if generation_id is not None:
        node.generation_run_id = generation_id
    if revision_id is not None:
        node.platform_variant_revision_id = revision_id
    if publication_id is not None:
        node.publication_id = publication_id

    if bool(projected_result.get("review_required")) and revision_id is not None:
        review = await _node_by_type(session, run, "human_review")
        if review is not None:
            if artifact is not None:
                review.input_summary = summary_with_artifact(projected_result, artifact)
                review.output_summary = summary_with_artifact(
                    {"status": "waiting_for_review"},
                    artifact,
                )
            review.status = "waiting_for_review"
            review.platform_variant_revision_id = revision_id
            review.started_at = observed_at
            run.status = "waiting_for_review"
            run.current_node_id = review.node_id
            session.add(
                WorkflowEvent(
                    workflow_job_id=job.id,
                    event_type="automation.run.waiting_for_review",
                    actor="automation",
                    event_data={"automation_run_id": str(run.id), "revision_id": str(revision_id)},
                )
            )
            return

    if job.job_type == "telegram.route.dry_run":
        run.status = "running"
        run.current_node_id = node.node_id
        return

    terminal = await _node_by_type(session, run, "save_drafts")
    if terminal is not None and terminal.status == "pending":
        terminal.status = "succeeded"
        terminal.started_at = observed_at
        terminal.finished_at = observed_at
        if artifact is not None:
            terminal.output_summary = summary_with_artifact({"status": "succeeded"}, artifact)
    publish = await _node_by_type(session, run, "telegram_publish")
    if publish is not None and publish.id == node.id:
        run.status = "succeeded"
    elif terminal is not None:
        run.status = "succeeded"
    if run.status == "succeeded":
        run.current_node_id = None
        run.finished_at = observed_at
        session.add(
            WorkflowEvent(
                workflow_job_id=job.id,
                event_type="automation.run.completed",
                actor="automation",
                event_data={"automation_run_id": str(run.id), "dry_run": run.dry_run},
            )
        )


async def sync_automation_job_failed(
    session: AsyncSession,
    *,
    job: WorkflowJob,
    error_code: str,
    error_message: str,
    observed_at: datetime,
    terminal: bool,
    waiting_for_review: bool,
) -> None:
    if job.automation_run_id is None or job.automation_node_run_id is None or not (terminal or waiting_for_review):
        return
    run = await session.scalar(select(AutomationRun).where(AutomationRun.id == job.automation_run_id).with_for_update())
    node = await session.scalar(
        select(AutomationNodeRun).where(AutomationNodeRun.id == job.automation_node_run_id).with_for_update()
    )
    if run is None or node is None:
        return
    node.status = "waiting_for_review" if waiting_for_review else "failed"
    node.safe_error_code = error_code
    node.safe_error_message = error_message
    node.finished_at = observed_at
    run.status = "waiting_for_review" if waiting_for_review else "failed"
    run.current_node_id = node.node_id
    run.safe_error_code = error_code
    run.safe_error_message = error_message
    run.finished_at = None if waiting_for_review else observed_at
    session.add(
        WorkflowEvent(
            workflow_job_id=job.id,
            event_type="automation.run.review_boundary" if waiting_for_review else "automation.run.failed",
            actor="automation",
            event_data={"automation_run_id": str(run.id), "error_code": error_code},
        )
    )


async def continue_automation_review(
    session: AsyncSession,
    *,
    revision_id: UUID,
    observed_at: datetime,
) -> None:
    review = await session.scalar(
        select(AutomationNodeRun)
        .where(
            AutomationNodeRun.platform_variant_revision_id == revision_id,
            AutomationNodeRun.status == "waiting_for_review",
        )
        .with_for_update()
    )
    if review is None:
        return
    run = await session.get(AutomationRun, review.automation_run_id)
    if run is None:
        return
    review.status = "succeeded"
    review.finished_at = observed_at
    input_artifact = normalize_artifact(
        review.input_summary,
        source_node_id=review.node_id,
        run_id=str(run.id),
    )
    publish = await _node_by_type(session, run, "telegram_publish")
    if input_artifact is not None:
        approved_artifact = review_artifact(
            input_artifact,
            approved=True,
            eligible_for_publication=publish is not None,
        )
        review.output_summary = summary_with_artifact(
            {"status": "approved"},
            approved_artifact,
        )
    if run.dry_run:
        run.status = "succeeded"
        run.current_node_id = None
        run.finished_at = observed_at
        return
    if publish is not None:
        publish.status = "pending"
        publish.platform_variant_revision_id = revision_id
        run.status = "running"
        run.current_node_id = publish.node_id


async def continue_automation_artifact_review(
    session: AsyncSession,
    *,
    run_id: UUID,
    observed_at: datetime,
) -> None:
    """Resume a capability-based review boundary, including non-platform artifacts."""

    run = await session.scalar(select(AutomationRun).where(AutomationRun.id == run_id).with_for_update())
    if run is None:
        return
    review = await _node_by_type(session, run, "human_review")
    if review is None or review.status != "waiting_for_review":
        return
    artifact = normalize_artifact(review.input_summary, source_node_id=review.node_id, run_id=str(run.id))
    if artifact is None:
        return
    order = (run.resource_snapshot or {}).get("node_order")
    node_types = (run.resource_snapshot or {}).get("node_types_by_id")
    if not isinstance(order, list) or not isinstance(node_types, dict):
        return
    try:
        review_index = order.index(review.node_id)
        next_node_id = order[review_index + 1]
    except (ValueError, IndexError):
        return
    if not isinstance(next_node_id, str):
        return
    next_node = await session.scalar(
        select(AutomationNodeRun)
        .where(
            AutomationNodeRun.automation_run_id == run.id,
            AutomationNodeRun.node_id == next_node_id,
        )
        .with_for_update()
    )
    if next_node is None:
        return
    eligible_for_publication = any(
        node_types.get(candidate) == "telegram_publish"
        for candidate in order[review_index + 1 :]
    )
    approved = review_artifact(
        artifact,
        approved=True,
        eligible_for_publication=eligible_for_publication,
    )
    pending_id = review.output_summary.get("continuation_job_id")
    review.status = "succeeded"
    review.finished_at = observed_at
    review.output_summary = summary_with_artifact({"status": "approved"}, approved)
    if run.dry_run:
        run.status = "succeeded"
        run.current_node_id = None
        run.finished_at = observed_at
        return
    continuation_id = _uuid(pending_id)
    if continuation_id is None:
        continuation_id = _uuid((review.input_summary or {}).get("continuation_job_id"))
    if continuation_id is None:
        return
    continuation = await session.get(WorkflowJob, continuation_id)
    if continuation is None:
        return
    continuation.status = "queued"
    continuation.scheduled_for = observed_at
    continuation.finished_at = None
    continuation.automation_run_id = run.id
    continuation.automation_node_run_id = next_node.id
    next_node.status = "queued"
    next_node.workflow_job_id = continuation.id
    next_node.input_summary = summary_with_artifact({}, approved)
    run.status = "running"
    run.current_node_id = next_node.node_id
    run.finished_at = None
    session.add(
        WorkflowEvent(
            workflow_job_id=continuation.id,
            event_type="automation.run.review_approved",
            actor="operator",
            event_data={"automation_run_id": str(run.id), "review_node_id": review.node_id},
        )
    )


async def bind_automation_publish_job(
    session: AsyncSession,
    *,
    revision_id: UUID,
    workflow_job: WorkflowJob,
    publish_job_id: UUID,
) -> None:
    node = await session.scalar(
        select(AutomationNodeRun)
        .where(AutomationNodeRun.platform_variant_revision_id == revision_id)
        .order_by(AutomationNodeRun.created_at.desc())
        .limit(1)
    )
    if node is None:
        return
    run = await session.get(AutomationRun, node.automation_run_id)
    if run is None:
        return
    if run.dry_run:
        raise ValueError("dry_run_publication_disabled")
    publish = await _node_by_type(session, run, "telegram_publish")
    if publish is None:
        return
    publish.status = "queued"
    publish.workflow_job_id = workflow_job.id
    publish.publish_job_id = publish_job_id
    publish.platform_variant_revision_id = revision_id
    workflow_job.automation_run_id = run.id
    workflow_job.automation_node_run_id = publish.id


__all__ = [
    "bind_automation_publish_job",
    "continue_automation_artifact_review",
    "continue_automation_review",
    "sync_automation_job_failed",
    "sync_automation_job_succeeded",
]
