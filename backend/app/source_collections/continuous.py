from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import IngestRun
from app.jobs.models import WorkflowJob
from app.jobs.repository import JobRepository
from app.source_collections.models import (
    CONTINUOUS_SUBSCRIPTION_ACTIVE_STATUSES,
    SourceCollection,
    SourceCollectionIngestionSubscription,
)


@dataclass(frozen=True, slots=True)
class ContinuousSubscriptionConflict(Exception):
    code: str
    message: str
    subscription_id: UUID | None = None

    def __str__(self) -> str:
        return self.message


def utc_now(value: datetime | None = None) -> datetime:
    observed = value or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("continuous ingestion clock must be timezone-aware")
    return observed.astimezone(UTC)


async def get_subscription(
    session: AsyncSession,
    subscription_id: UUID,
    *,
    lock: bool = False,
) -> SourceCollectionIngestionSubscription | None:
    statement = select(SourceCollectionIngestionSubscription).where(
        SourceCollectionIngestionSubscription.id == subscription_id
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def get_latest_subscription(
    session: AsyncSession,
    collection_id: UUID,
    *,
    lock: bool = False,
) -> SourceCollectionIngestionSubscription | None:
    statement = (
        select(SourceCollectionIngestionSubscription)
        .where(SourceCollectionIngestionSubscription.source_collection_id == collection_id)
        .order_by(
            SourceCollectionIngestionSubscription.created_at.desc(),
            SourceCollectionIngestionSubscription.id.desc(),
        )
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def start_subscription(
    session: AsyncSession,
    *,
    collection_id: UUID,
    idempotency_key: str,
    created_by: str = "operator",
    interval_minutes: int | None = None,
    now: datetime | None = None,
) -> tuple[SourceCollectionIngestionSubscription, bool]:
    observed_at = utc_now(now)
    effective_interval = (
        interval_minutes
        if interval_minutes is not None
        else settings.continuous_ingestion_interval_minutes
    )
    if not 1 <= effective_interval <= 1440:
        raise ValueError("continuous ingestion interval must be between 1 and 1440 minutes")
    collection = await session.scalar(
        select(SourceCollection)
        .where(SourceCollection.id == collection_id)
        .with_for_update()
    )
    if collection is None:
        raise LookupError("source collection not found")

    existing = await session.scalar(
        select(SourceCollectionIngestionSubscription)
        .where(SourceCollectionIngestionSubscription.idempotency_key == idempotency_key)
        .with_for_update()
    )
    if existing is not None:
        if existing.source_collection_id != collection_id:
            raise ContinuousSubscriptionConflict(
                code="continuous_ingestion_idempotency_key_reused",
                message="This continuous ingestion request was already used for another Source Collection.",
                subscription_id=existing.id,
            )
        return existing, True

    active = await session.scalar(
        select(SourceCollectionIngestionSubscription)
        .where(
            SourceCollectionIngestionSubscription.source_collection_id == collection_id,
            SourceCollectionIngestionSubscription.status.in_(CONTINUOUS_SUBSCRIPTION_ACTIVE_STATUSES),
        )
        .order_by(SourceCollectionIngestionSubscription.created_at.desc())
        .with_for_update()
    )
    if active is not None:
        raise ContinuousSubscriptionConflict(
            code="continuous_ingestion_already_running",
            message="Continuous ingestion is already active for this Source Collection.",
            subscription_id=active.id,
        )

    active_run = await session.scalar(
        select(IngestRun)
        .where(
            IngestRun.source_collection_id == collection_id,
            IngestRun.status.in_(("queued", "running")),
        )
        .with_for_update()
    )
    if active_run is not None:
        raise ContinuousSubscriptionConflict(
            code="collection_ingest_already_running",
            message="An ingestion run for this Source Collection is already active.",
        )

    subscription = SourceCollectionIngestionSubscription(
        id=uuid4(),
        source_collection_id=collection.id,
        source_collection_name_at_start=collection.name,
        mode="continuous",
        status="starting",
        interval_minutes=effective_interval,
        idempotency_key=idempotency_key,
        started_at=observed_at,
        next_cycle_at=observed_at,
        created_by=created_by,
    )
    session.add(subscription)
    await session.flush()
    return subscription, False


async def stop_subscription(
    session: AsyncSession,
    subscription_id: UUID,
    *,
    now: datetime | None = None,
    reason: str | None = None,
) -> SourceCollectionIngestionSubscription:
    observed_at = utc_now(now)
    subscription = await get_subscription(session, subscription_id, lock=True)
    if subscription is None:
        raise LookupError("continuous ingestion subscription not found")
    if subscription.status in {"stopped", "error"}:
        return subscription

    await _stop_one(session, subscription, observed_at=observed_at, reason=reason)
    await session.flush()
    return subscription


async def stop_subscriptions_for_collection_delete(
    session: AsyncSession,
    collection_id: UUID,
    *,
    now: datetime | None = None,
) -> None:
    observed_at = utc_now(now)
    subscriptions = list(
        await session.scalars(
            select(SourceCollectionIngestionSubscription)
            .where(
                SourceCollectionIngestionSubscription.source_collection_id == collection_id,
                SourceCollectionIngestionSubscription.status.in_(CONTINUOUS_SUBSCRIPTION_ACTIVE_STATUSES),
            )
            .with_for_update()
        )
    )
    for subscription in subscriptions:
        await _stop_one(
            session,
            subscription,
            observed_at=observed_at,
            reason="Source Collection was deleted.",
        )
    await session.flush()


async def _stop_one(
    session: AsyncSession,
    subscription: SourceCollectionIngestionSubscription,
    *,
    observed_at: datetime,
    reason: str | None,
) -> None:
    """Wind one subscription down, cancelling or handing off its current cycle.

    A queued cycle job is cancelled outright; a running one cannot be, so the
    subscription only asks it to stop and the worker finishes the handover.
    """

    job = None
    if subscription.current_cycle_job_id is not None:
        job = await session.scalar(
            select(WorkflowJob)
            .where(WorkflowJob.id == subscription.current_cycle_job_id)
            .with_for_update()
        )
    if job is not None and job.status == "running":
        subscription.status = "stopping"
        subscription.next_cycle_at = None
        if reason:
            subscription.last_error = reason
        return
    if job is not None and job.status == "queued":
        await JobRepository(session).cancel_job(job_id=job.id, now=observed_at)
    subscription.current_cycle_job_id = None
    subscription.current_cycle_run_id = None
    _mark_stopped(subscription, observed_at=observed_at, reason=reason)


def _mark_stopped(
    subscription: SourceCollectionIngestionSubscription,
    *,
    observed_at: datetime,
    reason: str | None,
) -> None:
    subscription.status = "stopped"
    subscription.stopped_at = observed_at
    subscription.next_cycle_at = None
    if reason:
        subscription.last_error = reason
