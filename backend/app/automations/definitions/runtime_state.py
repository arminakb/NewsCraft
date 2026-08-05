from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.models import AutomationNodeRun, AutomationRun
from app.core.redaction import redact_secrets
from app.jobs.models import WorkflowEvent, WorkflowJob


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value is not None else None
    except (ValueError, TypeError):
        return None


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
    if run.status in {"succeeded", "failed", "cancelled", "warning"} and node.status in {
        "succeeded",
        "failed",
        "skipped",
    }:
        # Some trigger handlers finish their run atomically while producing the
        # canonical trigger output. The projection wrapper must not append a
        # second completion event or overwrite that terminal state.
        return
    safe_result = redact_secrets(result)
    node.output_summary = safe_result if isinstance(safe_result, dict) else {}
    node.started_at = node.started_at or job.started_at or observed_at
    continuation_id = _uuid(result.get("continuation_job_id"))
    if continuation_id is not None:
        continuation = await session.get(WorkflowJob, continuation_id)
        if continuation is not None:
            target = node
            continuation_node_id = result.get("continuation_node_id")
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
    dispatch_id = _uuid(result.get("dispatch_id"))
    generation_id = _uuid(result.get("generation_run_id"))
    revision_id = _uuid(result.get("revision_id"))
    publication_id = _uuid(result.get("publication_id"))
    if dispatch_id is not None:
        node.automation_dispatch_id = dispatch_id
    if generation_id is not None:
        node.generation_run_id = generation_id
    if revision_id is not None:
        node.platform_variant_revision_id = revision_id
    if publication_id is not None:
        node.publication_id = publication_id

    if bool(result.get("review_required")) and revision_id is not None:
        review = await _node_by_type(session, run, "human_review")
        if review is not None:
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
    if run.dry_run:
        run.status = "succeeded"
        run.current_node_id = None
        run.finished_at = observed_at
        return
    publish = await _node_by_type(session, run, "telegram_publish")
    if publish is not None:
        publish.status = "pending"
        publish.platform_variant_revision_id = revision_id
        run.status = "running"
        run.current_node_id = publish.node_id


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
    "continue_automation_review",
    "sync_automation_job_failed",
    "sync_automation_job_succeeded",
]
