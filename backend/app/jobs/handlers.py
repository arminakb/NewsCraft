from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.db.models import IngestRun
from app.jobs.errors import PermanentJobError, RetryableJobError
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, job_payload_copy
from app.source_collections.continuous import get_subscription
from app.source_collections.models import SourceCollectionIngestionSubscription
from app.source_collections.repository import (
    collection_source_count,
    create_collection_ingest_snapshot,
    get_collection,
)


def _build_workflow():
    from app.ingestion.workflow import IngestionWorkflow

    return IngestionWorkflow()


def _build_job_repository(session):
    return JobRepository(session)


async def handle_ingest_collect(job: JobExecution, context: JobContext) -> dict[str, Any]:
    return await _handle_ingest_collect_payload(job, context, job_payload_copy(job))


async def _handle_ingest_collect_payload(
    job: JobExecution,
    context: JobContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    workflow = _build_workflow()
    workflow_kwargs: dict[str, Any] = {
        "session": context.session,
        "platforms": payload.get("platforms"),
        "source_ids": payload.get("source_ids"),
        "trigger": "workflow_job",
    }
    collection_run_id = payload.get("ingest_run_id")
    if collection_run_id:
        jobs = _build_job_repository(context.session)

        async def report_progress(progress: dict[str, Any]) -> None:
            source_count = max(0, int(progress.get("source_count", 0)))
            processed_count = max(0, int(progress.get("processed_count", 0)))
            percentage = round((processed_count / source_count) * 100) if source_count else 0
            await jobs.update_progress(
                job_id=job.id,
                worker_id=job.lease_owner,
                progress=percentage,
                progress_message=f"Processed {processed_count} of {source_count} sources",
            )

        workflow_kwargs["ingest_run_id"] = collection_run_id
        workflow_kwargs["on_progress"] = report_progress

    stats = await workflow.run(**workflow_kwargs)
    if int(stats.get("failed", 0)) > 0 and not collection_run_id:
        raise RetryableJobError(code="ingest_partial", message="One or more ingestion sources failed")
    await _build_job_repository(context.session).enqueue_job(
        job_type="story.group_pending",
        payload={"limit": 100, "root_ingest_job_id": str(job.id)},
        idempotency_key=f"story-group:{job.id}",
        origin=JobOrigin.AUTOMATION,
    )
    return stats


async def handle_source_collection_continuous_cycle(
    job: JobExecution,
    context: JobContext,
) -> dict[str, Any]:
    payload = job_payload_copy(job)
    try:
        subscription_id = UUID(str(payload.get("subscription_id")))
        cycle_number = int(payload.get("cycle_number"))
    except (TypeError, ValueError):
        raise PermanentJobError(
            code="continuous_cycle_payload_invalid",
            message="Continuous ingestion cycle payload is invalid.",
        ) from None
    if cycle_number < 1:
        raise PermanentJobError(
            code="continuous_cycle_number_invalid",
            message="Continuous ingestion cycle number is invalid.",
        )

    # Keep lock order collection -> subscription. Membership and collection
    # lifecycle mutations use the same order, preventing cross-operation waits.
    subscription_hint = await get_subscription(context.session, subscription_id)
    if subscription_hint is None:
        return {"status": "orphaned", "subscription_id": str(subscription_id)}
    collection = None
    if subscription_hint.source_collection_id is not None:
        collection = await get_collection(
            context.session,
            subscription_hint.source_collection_id,
            lock=True,
        )
    subscription = await get_subscription(context.session, subscription_id, lock=True)
    if subscription is None:
        return {"status": "orphaned", "subscription_id": str(subscription_id)}
    if subscription.cycle_count >= cycle_number and subscription.current_cycle_job_id is None:
        return {
            "status": "already_completed",
            "subscription_id": str(subscription.id),
            "cycle_number": cycle_number,
        }
    if subscription.status == "stopping":
        _stop_without_cycle(subscription, datetime.now(UTC))
        return {"status": "stopped", "subscription_id": str(subscription.id)}
    if subscription.status not in {"starting", "running"}:
        return {
            "status": subscription.status,
            "subscription_id": str(subscription.id),
        }
    if collection is None:
        _stop_without_cycle(
            subscription,
            datetime.now(UTC),
            last_cycle_status="collection_deleted",
            error="Source Collection was deleted.",
        )
        return {
            "status": "stopped",
            "subscription_id": str(subscription.id),
            "reason": "collection_deleted",
        }

    active_run = await context.session.scalar(
        select(IngestRun)
        .where(
            IngestRun.source_collection_id == collection.id,
            IngestRun.status.in_(("queued", "running")),
            (IngestRun.continuous_subscription_id.is_(None))
            | (IngestRun.continuous_subscription_id != subscription.id),
        )
        .with_for_update()
    )
    if active_run is not None:
        _defer_cycle(subscription, datetime.now(UTC), "waiting_for_collection")
        return {
            "status": "deferred",
            "subscription_id": str(subscription.id),
            "reason": "collection_busy",
        }

    run = None
    run_id_value = payload.get("ingest_run_id")
    if run_id_value:
        try:
            run = await context.session.get(IngestRun, UUID(str(run_id_value)))
        except (TypeError, ValueError):
            run = None
    if run is None:
        run = await context.session.scalar(
            select(IngestRun)
            .where(
                IngestRun.continuous_subscription_id == subscription.id,
                IngestRun.continuous_cycle_number == cycle_number,
            )
            .order_by(IngestRun.started_at.desc(), IngestRun.id.desc())
        )

    if run is None:
        if await collection_source_count(context.session, collection.id) == 0:
            _finish_cycle(
                subscription,
                cycle_number=cycle_number,
                observed_at=datetime.now(UTC),
                status="waiting_for_sources",
                successful=False,
            )
            return {
                "status": "waiting_for_sources",
                "subscription_id": str(subscription.id),
                "cycle_number": cycle_number,
            }
        try:
            run = await create_collection_ingest_snapshot(
                context.session,
                collection_id=collection.id,
                trigger="source_collection_continuous",
                parser_version=settings.parser_version,
            )
        except LookupError:
            _stop_without_cycle(
                subscription,
                datetime.now(UTC),
                last_cycle_status="collection_deleted",
                error="Source Collection was deleted.",
            )
            return {"status": "stopped", "subscription_id": str(subscription.id)}
        except ValueError as exc:
            if await collection_source_count(context.session, collection.id) == 0:
                _finish_cycle(
                    subscription,
                    cycle_number=cycle_number,
                    observed_at=datetime.now(UTC),
                    status="waiting_for_sources",
                    successful=False,
                )
                return {
                    "status": "waiting_for_sources",
                    "subscription_id": str(subscription.id),
                    "cycle_number": cycle_number,
                }
            raise RetryableJobError(code="continuous_snapshot_failed", message=str(exc)) from None
        run.continuous_subscription_id = subscription.id
        run.continuous_cycle_number = cycle_number
        await context.session.flush()

    subscription.current_cycle_run_id = run.id
    payload["ingest_run_id"] = str(run.id)
    payload["cycle_number"] = cycle_number
    await JobRepository(context.session).checkpoint_job(
        job_id=job.id,
        worker_id=job.lease_owner,
        payload=payload,
    )
    await context.session.commit()

    if run.status in {"succeeded", "partial", "failed"}:
        stats = dict(run.stats or {})
    else:
        stats = await _handle_ingest_collect_payload(job, context, payload)

    observed_at = datetime.now(UTC)
    failed = int(stats.get("failed", 0)) > 0 or run.status == "failed"
    _finish_cycle(
        subscription,
        cycle_number=cycle_number,
        observed_at=observed_at,
        status="partial" if failed else "succeeded",
        successful=not failed,
        error="One or more sources failed." if failed else None,
    )
    return {
        "status": "partial" if failed else "succeeded",
        "subscription_id": str(subscription.id),
        "cycle_number": cycle_number,
        "run_id": str(run.id),
        **stats,
    }


def _stop_without_cycle(
    subscription: SourceCollectionIngestionSubscription,
    observed_at: datetime,
    *,
    last_cycle_status: str = "stopped",
    error: str | None = None,
) -> None:
    subscription.status = "stopped"
    subscription.stopped_at = observed_at
    subscription.next_cycle_at = None
    subscription.current_cycle_job_id = None
    subscription.current_cycle_run_id = None
    subscription.last_cycle_status = last_cycle_status
    if error:
        subscription.last_error = error


def _defer_cycle(
    subscription: SourceCollectionIngestionSubscription,
    observed_at: datetime,
    status: str,
) -> None:
    subscription.status = "running"
    subscription.cycle_count = int(subscription.cycle_count) + 1
    subscription.last_cycle_at = observed_at
    subscription.last_cycle_status = status
    subscription.next_cycle_at = observed_at + timedelta(minutes=subscription.interval_minutes)
    subscription.current_cycle_job_id = None
    subscription.current_cycle_run_id = None


def _finish_cycle(
    subscription: SourceCollectionIngestionSubscription,
    *,
    cycle_number: int,
    observed_at: datetime,
    status: str,
    successful: bool,
    error: str | None = None,
) -> None:
    subscription.cycle_count = max(int(subscription.cycle_count), cycle_number)
    subscription.last_cycle_at = observed_at
    subscription.last_cycle_status = status
    subscription.last_success_at = observed_at if successful else subscription.last_success_at
    subscription.current_cycle_job_id = None
    subscription.current_cycle_run_id = None
    if error:
        subscription.last_error = error
    elif successful:
        subscription.last_error = None
    if subscription.status == "stopping":
        subscription.status = "stopped"
        subscription.stopped_at = observed_at
        subscription.next_cycle_at = None
    elif subscription.status in {"starting", "running"}:
        subscription.status = "running"
        subscription.next_cycle_at = observed_at + timedelta(minutes=subscription.interval_minutes)
