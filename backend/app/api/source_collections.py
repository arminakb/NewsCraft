from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import IngestRun
from app.db.session import get_session
from app.jobs.models import WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin
from app.source_collections.continuous import (
    ContinuousSubscriptionConflict,
    get_latest_subscription,
    get_subscription,
    start_subscription,
    stop_subscription,
    stop_subscriptions_for_collection_delete,
)
from app.source_collections.models import (
    CONTINUOUS_SUBSCRIPTION_ACTIVE_STATUSES,
    SOURCE_COLLECTION_MAX_SIZE,
    IngestRunSourceSnapshot,
    SourceCollectionIngestionSubscription,
)
from app.source_collections.repository import (
    SourceCollectionLimitExceeded,
    add_members,
    collection_source_count,
    create_collection,
    create_collection_ingest_snapshot,
    get_collection,
    get_collection_projection,
    list_collections,
    remove_members,
    update_collection,
)
from app.source_collections.repository import (
    list_sources as list_collection_sources_page,
)
from app.source_collections.schemas import (
    CollectionIngestAcceptedOut,
    IngestRunSnapshotSourceOut,
    SourceCollectionContinuousStartIn,
    SourceCollectionCreateIn,
    SourceCollectionIngestIn,
    SourceCollectionMembershipBulkIn,
    SourceCollectionMembershipChangeOut,
    SourceCollectionOut,
    SourceCollectionRunOut,
    SourceCollectionRunPageOut,
    SourceCollectionSubscriptionOut,
    SourceCollectionUpdateIn,
    SourcePageOut,
)

router = APIRouter(prefix="/source-collections", tags=["source-collections"])
SessionDependency = Depends(get_session)


def _collection_out(row: Mapping[str, Any]) -> SourceCollectionOut:
    return SourceCollectionOut(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        source_count=int(row["source_count"] or 0),
        maximum_sources=SOURCE_COLLECTION_MAX_SIZE,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        active_ingest_run_id=row.get("active_ingest_run_id"),
        active_ingest_status=row.get("active_ingest_status"),
        active_ingest_source_count=row.get("active_ingest_source_count"),
        active_ingest_processed_count=row.get("active_ingest_processed_count"),
        active_ingest_success_count=row.get("active_ingest_success_count"),
        active_ingest_failure_count=row.get("active_ingest_failure_count"),
        continuous_subscription_id=row.get("continuous_subscription_id"),
        continuous_mode=row.get("continuous_mode"),
        continuous_status=row.get("continuous_status"),
        continuous_interval_minutes=row.get("continuous_interval_minutes"),
        continuous_started_at=row.get("continuous_started_at"),
        continuous_stopped_at=row.get("continuous_stopped_at"),
        continuous_last_cycle_at=row.get("continuous_last_cycle_at"),
        continuous_next_cycle_at=row.get("continuous_next_cycle_at"),
        continuous_last_success_at=row.get("continuous_last_success_at"),
        continuous_cycle_count=row.get("continuous_cycle_count"),
        continuous_last_cycle_status=row.get("continuous_last_cycle_status"),
        continuous_last_error=row.get("continuous_last_error"),
        continuous_current_cycle_job_id=row.get("continuous_current_cycle_job_id"),
        continuous_current_cycle_run_id=row.get("continuous_current_cycle_run_id"),
    )


def _source_page_out(page) -> SourcePageOut:
    return SourcePageOut(
        items=list(page.items),
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


def _collection_conflict(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "source_collection_conflict",
            "message": message,
        },
    )


@router.get("", response_model=list[SourceCollectionOut])
async def list_source_collections(session: AsyncSession = SessionDependency) -> list[SourceCollectionOut]:
    return [_collection_out(row) for row in await list_collections(session)]


@router.post("", response_model=SourceCollectionOut, status_code=status.HTTP_201_CREATED)
async def create_source_collection(
    body: SourceCollectionCreateIn,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionOut:
    try:
        async with session.begin_nested():
            created = await create_collection(session, name=body.name, description=body.description)
    except ValueError as exc:
        raise _collection_conflict(str(exc)) from None
    await session.commit()
    projection = await get_collection_projection(session, created.id)
    if projection is None:  # pragma: no cover - commit/query contract
        raise HTTPException(status_code=500, detail="source collection was not created")
    return _collection_out(projection)


@router.get("/unassigned/sources", response_model=SourcePageOut)
async def list_unassigned_sources(
    search: str | None = Query(default=None, max_length=200),
    platform: str | None = Query(default=None, max_length=64),
    source_group: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDependency,
) -> SourcePageOut:
    return _source_page_out(
        await list_collection_sources_page(
            session,
            unassigned=True,
            search=search,
            platform=platform,
            source_group=source_group,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/{collection_id}", response_model=SourceCollectionOut)
async def get_source_collection(
    collection_id: UUID,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionOut:
    projection = await get_collection_projection(session, collection_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="source collection not found")
    return _collection_out(projection)


@router.patch("/{collection_id}", response_model=SourceCollectionOut)
async def update_source_collection(
    collection_id: UUID,
    body: SourceCollectionUpdateIn,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionOut:
    collection = await get_collection(session, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="source collection not found")
    try:
        async with session.begin_nested():
            await update_collection(
                session,
                collection,
                name=body.name,
                description=body.description,
                description_provided="description" in body.model_fields_set,
            )
    except ValueError as exc:
        raise _collection_conflict(str(exc)) from None
    await session.commit()
    projection = await get_collection_projection(session, collection_id)
    if projection is None:  # pragma: no cover - collection was just updated
        raise HTTPException(status_code=404, detail="source collection not found")
    return _collection_out(projection)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_collection(collection_id: UUID, session: AsyncSession = SessionDependency) -> Response:
    collection = await get_collection(session, collection_id, lock=True)
    if collection is None:
        raise HTTPException(status_code=404, detail="source collection not found")
    await stop_subscriptions_for_collection_delete(session, collection_id, now=datetime.now(UTC))
    await session.delete(collection)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{collection_id}/sources", response_model=SourcePageOut)
async def list_collection_sources(
    collection_id: UUID,
    search: str | None = Query(default=None, max_length=200),
    platform: str | None = Query(default=None, max_length=64),
    source_group: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDependency,
) -> SourcePageOut:
    if await get_collection(session, collection_id) is None:
        raise HTTPException(status_code=404, detail="source collection not found")
    return _source_page_out(
        await list_collection_sources_page(
            session,
            collection_id=collection_id,
            search=search,
            platform=platform,
            source_group=source_group,
            limit=limit,
            offset=offset,
        )
    )


@router.post("/{collection_id}/sources", response_model=SourceCollectionMembershipChangeOut)
async def add_collection_sources(
    collection_id: UUID,
    body: SourceCollectionMembershipBulkIn,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionMembershipChangeOut:
    try:
        change = await add_members(session, collection_id, body.source_ids)
    except LookupError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="source collection not found") from None
    except SourceCollectionLimitExceeded as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "source_collection_limit_exceeded",
                "message": str(exc),
                "collection_id": str(exc.collection_id),
                "current_count": exc.current_count,
                "requested_additions": exc.requested_additions,
                "maximum": SOURCE_COLLECTION_MAX_SIZE,
            },
        ) from None
    await session.commit()
    return SourceCollectionMembershipChangeOut(
        collection_id=change.collection_id,
        added_source_ids=list(change.added_source_ids),
        already_member_source_ids=list(change.already_member_source_ids),
        missing_source_ids=list(change.missing_source_ids),
        source_count=change.source_count,
        maximum_sources=SOURCE_COLLECTION_MAX_SIZE,
    )


@router.delete("/{collection_id}/sources", response_model=SourceCollectionMembershipChangeOut)
async def remove_collection_sources(
    collection_id: UUID,
    body: SourceCollectionMembershipBulkIn,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionMembershipChangeOut:
    try:
        change = await remove_members(session, collection_id, body.source_ids)
    except LookupError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="source collection not found") from None
    await session.commit()
    return SourceCollectionMembershipChangeOut(
        collection_id=change.collection_id,
        removed_source_ids=list(change.removed_source_ids),
        already_member_source_ids=list(change.already_member_source_ids),
        source_count=change.source_count,
        maximum_sources=SOURCE_COLLECTION_MAX_SIZE,
    )


@router.post("/{collection_id}/ingest", response_model=CollectionIngestAcceptedOut, status_code=202)
async def start_source_collection_ingest(
    collection_id: UUID,
    body: SourceCollectionIngestIn | None = Body(default=None),  # noqa: B008
    request_id: UUID | None = Query(default=None),  # noqa: B008
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    session: AsyncSession = SessionDependency,
) -> CollectionIngestAcceptedOut:
    request_token = (
        str(body.request_id)
        if body is not None and body.request_id is not None
        else str(request_id)
        if request_id is not None
        else idempotency_header
    )
    if not request_token:
        raise HTTPException(status_code=422, detail="request_id or Idempotency-Key is required")
    mode = body.mode if body is not None else "once"
    if mode == "continuous":
        try:
            subscription, deduplicated = await start_subscription(
                session,
                collection_id=collection_id,
                idempotency_key=f"manual:source-collection-continuous:{collection_id}:{request_token}",
                now=datetime.now(UTC),
            )
        except LookupError:
            await session.rollback()
            raise HTTPException(status_code=404, detail="source collection not found") from None
        except ContinuousSubscriptionConflict as exc:
            await session.rollback()
            detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
            if exc.subscription_id is not None:
                detail["subscription_id"] = str(exc.subscription_id)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None
        source_count = await collection_source_count(session, collection_id)
        await session.commit()
        return _accepted_continuous(subscription, source_count=source_count, deduplicated=deduplicated)

    idempotency_key = f"manual:source-collection:{collection_id}:{request_token}"
    jobs = JobRepository(session)
    existing_job = await jobs.get_by_idempotency_key(idempotency_key)
    if existing_job is not None:
        run_id = _run_id_from_job(existing_job)
        if run_id is not None:
            run = await session.get(IngestRun, run_id)
            if run is not None:
                return _accepted(run, existing_job.id, collection_id=collection_id, deduplicated=True)

    collection = await get_collection(session, collection_id, lock=True)
    if collection is None:
        raise HTTPException(status_code=404, detail="source collection not found")
    active_subscription = await session.scalar(
        select(SourceCollectionIngestionSubscription)
        .where(
            SourceCollectionIngestionSubscription.source_collection_id == collection_id,
            SourceCollectionIngestionSubscription.status.in_(CONTINUOUS_SUBSCRIPTION_ACTIVE_STATUSES),
        )
        .with_for_update()
    )
    if active_subscription is not None:
        active_subscription_id = active_subscription.id
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "continuous_ingestion_already_running",
                "message": "Continuous ingestion is already active for this Source Collection.",
                "collection_id": str(collection_id),
                "subscription_id": str(active_subscription_id),
            },
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
        active_run_id = active_run.id
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "collection_ingest_already_running",
                "message": "An ingestion run for this Source Collection is already active.",
                "collection_id": str(collection_id),
                "run_id": str(active_run_id),
            },
        )
    try:
        run = await create_collection_ingest_snapshot(
            session,
            collection_id=collection_id,
            trigger="source_collection_manual",
            parser_version=settings.parser_version,
        )
    except LookupError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="source collection not found") from None
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "source_collection_empty",
                "message": str(exc),
                "collection_id": str(collection_id),
            },
        ) from None
    result = await jobs.enqueue_job(
        job_type="ingest.collect",
        payload={
            "ingest_run_id": str(run.id),
            "source_collection_id": str(collection_id),
        },
        idempotency_key=idempotency_key,
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
    )
    await session.commit()
    return _accepted(
        run,
        result.job.id,
        collection_id=collection_id,
        deduplicated=not result.created,
    )


@router.post(
    "/{collection_id}/continuous",
    response_model=SourceCollectionSubscriptionOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_source_collection_continuous(
    collection_id: UUID,
    body: SourceCollectionContinuousStartIn | None = Body(default=None),  # noqa: B008
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    session: AsyncSession = SessionDependency,
) -> SourceCollectionSubscriptionOut:
    request_token = str(body.request_id) if body and body.request_id else idempotency_header
    if not request_token:
        raise HTTPException(status_code=422, detail="request_id or Idempotency-Key is required")
    try:
        subscription, _deduplicated = await start_subscription(
            session,
            collection_id=collection_id,
            idempotency_key=f"manual:source-collection-continuous:{collection_id}:{request_token}",
            now=datetime.now(UTC),
        )
    except LookupError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="source collection not found") from None
    except ContinuousSubscriptionConflict as exc:
        await session.rollback()
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.subscription_id is not None:
            detail["subscription_id"] = str(exc.subscription_id)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None
    await session.commit()
    return _subscription_out(subscription, source_collection_name=subscription.source_collection_name_at_start)


@router.get("/{collection_id}/continuous", response_model=SourceCollectionSubscriptionOut)
async def get_source_collection_continuous(
    collection_id: UUID,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionSubscriptionOut:
    subscription = await get_latest_subscription(session, collection_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="continuous ingestion subscription not found")
    collection = await get_collection(session, collection_id)
    collection_name = collection.name if collection is not None else subscription.source_collection_name_at_start
    return _subscription_out(
        subscription,
        source_collection_name=collection_name,
    )


@router.post("/{collection_id}/continuous/stop", response_model=SourceCollectionSubscriptionOut)
async def stop_source_collection_continuous(
    collection_id: UUID,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionSubscriptionOut:
    subscription = await get_latest_subscription(session, collection_id, lock=False)
    if subscription is None:
        raise HTTPException(status_code=404, detail="continuous ingestion subscription not found")
    try:
        stopped = await stop_subscription(
            session,
            subscription.id,
            now=datetime.now(UTC),
            reason="Stopped by operator.",
        )
    except LookupError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="continuous ingestion subscription not found") from None
    await session.commit()
    collection = await get_collection(session, collection_id)
    return _subscription_out(
        stopped,
        source_collection_name=collection.name if collection is not None else stopped.source_collection_name_at_start,
    )


@router.get("/continuous-subscriptions/{subscription_id}", response_model=SourceCollectionSubscriptionOut)
async def get_source_collection_subscription(
    subscription_id: UUID,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionSubscriptionOut:
    subscription = await get_subscription(session, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="continuous ingestion subscription not found")
    collection_name = subscription.source_collection_name_at_start
    if subscription.source_collection_id is not None:
        collection = await get_collection(session, subscription.source_collection_id)
        if collection is not None:
            collection_name = collection.name
    return _subscription_out(subscription, source_collection_name=collection_name)


@router.post(
    "/continuous-subscriptions/{subscription_id}/stop",
    response_model=SourceCollectionSubscriptionOut,
)
async def stop_source_collection_subscription(
    subscription_id: UUID,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionSubscriptionOut:
    try:
        subscription = await stop_subscription(
            session,
            subscription_id,
            now=datetime.now(UTC),
            reason="Stopped by operator.",
        )
    except LookupError:
        await session.rollback()
        raise HTTPException(status_code=404, detail="continuous ingestion subscription not found") from None
    await session.commit()
    collection_name = subscription.source_collection_name_at_start
    if subscription.source_collection_id is not None:
        collection = await get_collection(session, subscription.source_collection_id)
        if collection is not None:
            collection_name = collection.name
    return _subscription_out(subscription, source_collection_name=collection_name)


@router.get("/{collection_id}/runs", response_model=SourceCollectionRunPageOut)
async def list_source_collection_runs(
    collection_id: UUID,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = SessionDependency,
) -> SourceCollectionRunPageOut:
    if await get_collection(session, collection_id) is None:
        raise HTTPException(status_code=404, detail="source collection not found")
    total = int(
        await session.scalar(
            select(func.count()).select_from(IngestRun).where(IngestRun.source_collection_id == collection_id)
        )
        or 0
    )
    runs = list(
        await session.scalars(
            select(IngestRun)
            .where(IngestRun.source_collection_id == collection_id)
            .order_by(IngestRun.started_at.desc(), IngestRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return SourceCollectionRunPageOut(
        items=[_run_out(run, snapshots=[]) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(runs) < total,
    )


@router.get("/{collection_id}/runs/{run_id}", response_model=SourceCollectionRunOut)
async def get_source_collection_run(
    collection_id: UUID,
    run_id: UUID,
    session: AsyncSession = SessionDependency,
) -> SourceCollectionRunOut:
    run = await session.scalar(
        select(IngestRun).where(IngestRun.id == run_id, IngestRun.source_collection_id == collection_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="source collection ingest run not found")
    snapshots = list(
        await session.scalars(
            select(IngestRunSourceSnapshot)
            .where(IngestRunSourceSnapshot.ingest_run_id == run.id)
            .order_by(IngestRunSourceSnapshot.position)
        )
    )
    return _run_out(
        run,
        snapshots=[IngestRunSnapshotSourceOut.model_validate(snapshot) for snapshot in snapshots],
    )


def _run_out(
    run: IngestRun,
    *,
    snapshots: list[IngestRunSnapshotSourceOut],
) -> SourceCollectionRunOut:
    processed_successes = max(0, min(run.success_count, run.processed_count - run.failure_count))
    skipped_count = min(max(0, int((run.stats or {}).get("skipped", 0))), processed_successes)
    return SourceCollectionRunOut(
        id=run.id,
        source_collection_id=run.source_collection_id,
        source_collection_name_at_start=run.source_collection_name_at_start,
        source_count=run.source_count,
        processed_count=run.processed_count,
        success_count=processed_successes - skipped_count,
        failure_count=run.failure_count,
        skipped_count=skipped_count,
        started_at=run.started_at,
        completed_at=run.finished_at,
        status=run.status,
        trigger=run.trigger,
        mode="continuous" if run.continuous_subscription_id is not None else "once",
        continuous_subscription_id=run.continuous_subscription_id,
        continuous_cycle_number=run.continuous_cycle_number,
        stats=run.stats,
        error=run.error,
        sources=snapshots,
    )


def _run_id_from_job(job: WorkflowJob) -> UUID | None:
    value = job.payload.get("ingest_run_id") if isinstance(job.payload, dict) else None
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _accepted(
    run: IngestRun,
    job_id: UUID,
    *,
    collection_id: UUID,
    deduplicated: bool,
) -> CollectionIngestAcceptedOut:
    return CollectionIngestAcceptedOut(
        job_id=job_id,
        run_id=run.id,
        source_collection_id=run.source_collection_id or collection_id,
        source_collection_name=run.source_collection_name_at_start or "Source Collection",
        source_count=run.source_count,
        status="queued" if run.status == "queued" else run.status,
        deduplicated=deduplicated,
        mode="once",
    )


def _accepted_continuous(
    subscription,
    *,
    source_count: int,
    deduplicated: bool,
) -> CollectionIngestAcceptedOut:
    return CollectionIngestAcceptedOut(
        job_id=subscription.current_cycle_job_id,
        run_id=subscription.current_cycle_run_id,
        source_collection_id=subscription.source_collection_id,
        source_collection_name=subscription.source_collection_name_at_start or "Source Collection",
        source_count=source_count,
        status=subscription.status,
        deduplicated=deduplicated,
        mode="continuous",
        subscription_id=subscription.id,
        interval_minutes=subscription.interval_minutes,
        next_cycle_at=subscription.next_cycle_at,
    )


def _subscription_out(
    subscription,
    *,
    source_collection_name: str | None,
) -> SourceCollectionSubscriptionOut:
    return SourceCollectionSubscriptionOut(
        id=subscription.id,
        source_collection_id=subscription.source_collection_id,
        source_collection_name=source_collection_name,
        mode=subscription.mode,
        status=subscription.status,
        created_at=subscription.created_at,
        started_at=subscription.started_at,
        stopped_at=subscription.stopped_at,
        last_cycle_at=subscription.last_cycle_at,
        next_cycle_at=subscription.next_cycle_at,
        last_success_at=subscription.last_success_at,
        cycle_count=subscription.cycle_count,
        interval_minutes=subscription.interval_minutes,
        created_by=subscription.created_by,
        last_cycle_status=subscription.last_cycle_status,
        last_error=subscription.last_error,
        current_cycle_job_id=subscription.current_cycle_job_id,
        current_cycle_run_id=subscription.current_cycle_run_id,
    )
