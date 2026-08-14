from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IngestRun, Source
from app.ingestion.runs import new_ingest_run
from app.source_collections.models import (
    SOURCE_COLLECTION_MAX_SIZE,
    IngestRunSourceSnapshot,
    SourceCollection,
    SourceCollectionIngestionSubscription,
    SourceCollectionMembership,
)


def normalize_source_collection_name(value: str) -> tuple[str, str]:
    name = value.strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("source collection name must contain between 1 and 60 characters")
    return name, name.casefold()


def normalize_description(value: str | None) -> str | None:
    if value is None:
        return None
    description = value.strip()
    if len(description) > 500:
        raise ValueError("source collection description must contain at most 500 characters")
    return description or None


@dataclass(frozen=True, slots=True)
class SourceCollectionPage:
    items: tuple[Source, ...]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


@dataclass(frozen=True, slots=True)
class MembershipChange:
    collection_id: UUID
    added_source_ids: tuple[UUID, ...] = ()
    removed_source_ids: tuple[UUID, ...] = ()
    already_member_source_ids: tuple[UUID, ...] = ()
    missing_source_ids: tuple[UUID, ...] = ()
    source_count: int = 0


def collection_projection() -> Select:
    active_run = (
        select(
            IngestRun.source_collection_id,
            IngestRun.id.label("active_ingest_run_id"),
            IngestRun.status.label("active_ingest_status"),
            IngestRun.source_count.label("active_ingest_source_count"),
            IngestRun.processed_count.label("active_ingest_processed_count"),
            IngestRun.success_count.label("active_ingest_success_count"),
            IngestRun.failure_count.label("active_ingest_failure_count"),
        )
        .where(IngestRun.status.in_(("queued", "running")))
        .subquery()
    )
    latest_subscription = (
        select(
            SourceCollectionIngestionSubscription.source_collection_id,
            SourceCollectionIngestionSubscription.id.label("continuous_subscription_id"),
            SourceCollectionIngestionSubscription.mode.label("continuous_mode"),
            SourceCollectionIngestionSubscription.status.label("continuous_status"),
            SourceCollectionIngestionSubscription.interval_minutes.label("continuous_interval_minutes"),
            SourceCollectionIngestionSubscription.started_at.label("continuous_started_at"),
            SourceCollectionIngestionSubscription.stopped_at.label("continuous_stopped_at"),
            SourceCollectionIngestionSubscription.last_cycle_at.label("continuous_last_cycle_at"),
            SourceCollectionIngestionSubscription.next_cycle_at.label("continuous_next_cycle_at"),
            SourceCollectionIngestionSubscription.last_success_at.label("continuous_last_success_at"),
            SourceCollectionIngestionSubscription.cycle_count.label("continuous_cycle_count"),
            SourceCollectionIngestionSubscription.last_cycle_status.label("continuous_last_cycle_status"),
            SourceCollectionIngestionSubscription.last_error.label("continuous_last_error"),
            SourceCollectionIngestionSubscription.current_cycle_job_id.label("continuous_current_cycle_job_id"),
            SourceCollectionIngestionSubscription.current_cycle_run_id.label("continuous_current_cycle_run_id"),
            func.row_number()
            .over(
                partition_by=SourceCollectionIngestionSubscription.source_collection_id,
                order_by=(
                    SourceCollectionIngestionSubscription.created_at.desc(),
                    SourceCollectionIngestionSubscription.id.desc(),
                ),
            )
            .label("continuous_subscription_rank"),
        )
        .subquery()
    )
    projection = (
        active_run.c.active_ingest_run_id,
        active_run.c.active_ingest_status,
        active_run.c.active_ingest_source_count,
        active_run.c.active_ingest_processed_count,
        active_run.c.active_ingest_success_count,
        active_run.c.active_ingest_failure_count,
        latest_subscription.c.continuous_subscription_id,
        latest_subscription.c.continuous_mode,
        latest_subscription.c.continuous_status,
        latest_subscription.c.continuous_interval_minutes,
        latest_subscription.c.continuous_started_at,
        latest_subscription.c.continuous_stopped_at,
        latest_subscription.c.continuous_last_cycle_at,
        latest_subscription.c.continuous_next_cycle_at,
        latest_subscription.c.continuous_last_success_at,
        latest_subscription.c.continuous_cycle_count,
        latest_subscription.c.continuous_last_cycle_status,
        latest_subscription.c.continuous_last_error,
        latest_subscription.c.continuous_current_cycle_job_id,
        latest_subscription.c.continuous_current_cycle_run_id,
    )
    return (
        select(
            SourceCollection.id,
            SourceCollection.name,
            SourceCollection.normalized_name,
            SourceCollection.description,
            SourceCollection.created_at,
            SourceCollection.updated_at,
            func.count(SourceCollectionMembership.source_id).label("source_count"),
            *projection,
        )
        .outerjoin(
            SourceCollectionMembership,
            SourceCollectionMembership.collection_id == SourceCollection.id,
        )
        .outerjoin(
            active_run,
            active_run.c.source_collection_id == SourceCollection.id,
        )
        .outerjoin(
            latest_subscription,
            (latest_subscription.c.source_collection_id == SourceCollection.id)
            & (latest_subscription.c.continuous_subscription_rank == 1),
        )
        .group_by(
            SourceCollection.id,
            *projection,
        )
    )


def source_page_query(
    *,
    collection_id: UUID | None = None,
    unassigned: bool = False,
    search: str | None = None,
    platform: str | None = None,
    source_group: str | None = None,
    exclude_collection_id: UUID | None = None,
) -> Select[tuple[Source]]:
    statement = select(Source).where(Source.deleted_at.is_(None))
    if collection_id is not None and exclude_collection_id is None:
        statement = statement.join(
            SourceCollectionMembership,
            SourceCollectionMembership.source_id == Source.id,
        ).where(SourceCollectionMembership.collection_id == collection_id)
    elif unassigned and exclude_collection_id is None:
        statement = statement.outerjoin(
            SourceCollectionMembership,
            SourceCollectionMembership.source_id == Source.id,
        ).where(SourceCollectionMembership.source_id.is_(None))
    if exclude_collection_id is not None:
        statement = statement.outerjoin(
            SourceCollectionMembership,
            (SourceCollectionMembership.source_id == Source.id)
            & (SourceCollectionMembership.collection_id == exclude_collection_id),
        ).where(SourceCollectionMembership.source_id.is_(None))
    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Source.name.ilike(pattern),
                Source.feed_url.ilike(pattern),
                Source.telegram_username.ilike(pattern),
                Source.source_group.ilike(pattern),
            )
        )
    if platform:
        statement = statement.where(Source.platform == platform)
    if source_group:
        statement = statement.where(Source.source_group == source_group)
    return statement.order_by(Source.source_group, Source.name, Source.id)


async def list_collections(session: AsyncSession) -> list[Mapping[str, Any]]:
    rows = (
        (
            await session.execute(
                collection_projection().order_by(
                    SourceCollection.normalized_name,
                    SourceCollection.id,
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def get_collection_projection(session: AsyncSession, collection_id: UUID) -> Mapping[str, Any] | None:
    row = (
        (
            await session.execute(
                collection_projection().where(SourceCollection.id == collection_id)
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else dict(row)


async def get_collection(session: AsyncSession, collection_id: UUID, *, lock: bool = False) -> SourceCollection | None:
    statement = select(SourceCollection).where(SourceCollection.id == collection_id)
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def list_sources(
    session: AsyncSession,
    *,
    collection_id: UUID | None = None,
    unassigned: bool = False,
    search: str | None = None,
    platform: str | None = None,
    source_group: str | None = None,
    exclude_collection_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SourceCollectionPage:
    base = source_page_query(
        collection_id=collection_id,
        unassigned=unassigned,
        search=search,
        platform=platform,
        source_group=source_group,
        exclude_collection_id=exclude_collection_id,
    )
    count_statement = select(func.count()).select_from(base.order_by(None).subquery())
    total = int(await session.scalar(count_statement) or 0)
    rows = list(await session.scalars(base.limit(limit).offset(offset)))
    return SourceCollectionPage(items=tuple(rows), total=total, limit=limit, offset=offset)


async def collection_source_count(session: AsyncSession, collection_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(SourceCollectionMembership)
            .join(Source, Source.id == SourceCollectionMembership.source_id)
            .where(
                SourceCollectionMembership.collection_id == collection_id,
                Source.deleted_at.is_(None),
            )
        )
        or 0
    )


async def create_collection(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
) -> SourceCollection:
    normalized_name = normalize_source_collection_name(name)
    collection = SourceCollection(
        id=uuid4(),
        name=normalized_name[0],
        normalized_name=normalized_name[1],
        description=normalize_description(description),
    )
    session.add(collection)
    try:
        await session.flush()
    except IntegrityError:
        raise ValueError("source collection name already exists") from None
    return collection


async def update_collection(
    session: AsyncSession,
    collection: SourceCollection,
    *,
    name: str | None,
    description: str | None,
    description_provided: bool,
) -> SourceCollection:
    if name is not None:
        normalized_name = normalize_source_collection_name(name)
        collection.name = normalized_name[0]
        collection.normalized_name = normalized_name[1]
    if description_provided:
        collection.description = normalize_description(description)
    try:
        await session.flush()
    except IntegrityError:
        raise ValueError("source collection name already exists") from None
    return collection


async def add_members(
    session: AsyncSession,
    collection_id: UUID,
    source_ids: Sequence[UUID],
) -> MembershipChange:
    collection = await get_collection(session, collection_id, lock=True)
    if collection is None:
        raise LookupError("source collection not found")

    requested = tuple(dict.fromkeys(source_ids))
    current_ids = set(
        await session.scalars(
            select(SourceCollectionMembership.source_id).where(
                SourceCollectionMembership.collection_id == collection_id
            )
        )
    )
    source_rows = list(
        await session.scalars(
            select(Source.id).where(Source.id.in_(requested), Source.deleted_at.is_(None))
        )
    )
    valid_ids = set(source_rows)
    missing_ids = tuple(source_id for source_id in requested if source_id not in valid_ids)
    already_member_ids = tuple(source_id for source_id in requested if source_id in current_ids)
    additions = tuple(
        source_id for source_id in requested if source_id in valid_ids and source_id not in current_ids
    )
    current_count = len(current_ids)
    if current_count + len(additions) > SOURCE_COLLECTION_MAX_SIZE:
        raise SourceCollectionLimitExceeded(
            collection_id=collection_id,
            current_count=current_count,
            requested_additions=len(additions),
        )

    if additions:
        await session.execute(
            insert(SourceCollectionMembership)
            .values(
                [
                    {"collection_id": collection_id, "source_id": source_id}
                    for source_id in additions
                ]
            )
            .on_conflict_do_nothing(index_elements=["collection_id", "source_id"])
        )
    return MembershipChange(
        collection_id=collection_id,
        added_source_ids=additions,
        already_member_source_ids=already_member_ids,
        missing_source_ids=missing_ids,
        source_count=current_count + len(additions),
    )


async def remove_members(
    session: AsyncSession,
    collection_id: UUID,
    source_ids: Sequence[UUID],
) -> MembershipChange:
    collection = await get_collection(session, collection_id, lock=True)
    if collection is None:
        raise LookupError("source collection not found")
    requested = tuple(dict.fromkeys(source_ids))
    existing = set(
        await session.scalars(
            select(SourceCollectionMembership.source_id).where(
                SourceCollectionMembership.collection_id == collection_id,
                SourceCollectionMembership.source_id.in_(requested),
            )
        )
    )
    removed = tuple(source_id for source_id in requested if source_id in existing)
    if removed:
        await session.execute(
            delete(SourceCollectionMembership).where(
                SourceCollectionMembership.collection_id == collection_id,
                SourceCollectionMembership.source_id.in_(removed),
            )
        )
    current_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SourceCollectionMembership)
            .where(SourceCollectionMembership.collection_id == collection_id)
        )
        or 0
    )
    return MembershipChange(
        collection_id=collection_id,
        removed_source_ids=removed,
        already_member_source_ids=tuple(source_id for source_id in requested if source_id not in existing),
        source_count=current_count,
    )


async def create_collection_ingest_snapshot(
    session: AsyncSession,
    *,
    collection_id: UUID,
    trigger: str,
    parser_version: str,
) -> IngestRun:
    collection = await get_collection(session, collection_id, lock=True)
    if collection is None:
        raise LookupError("source collection not found")

    members = list(
        await session.scalars(
            select(Source)
            .join(SourceCollectionMembership, SourceCollectionMembership.source_id == Source.id)
            .where(
                SourceCollectionMembership.collection_id == collection_id,
                Source.deleted_at.is_(None),
            )
            .order_by(Source.source_group, Source.name, Source.id)
        )
    )
    if not members:
        raise ValueError("source collection must contain at least one source")

    now = datetime.now(UTC)
    run = new_ingest_run(
        run_id=uuid4(),
        started_at=now,
        trigger=trigger,
        parser_version=parser_version,
        status="queued",
        source_collection_id=collection.id,
        source_collection_name_at_start=collection.name,
        source_count=len(members),
    )
    session.add(run)
    await session.flush()
    session.add_all(
        [
            IngestRunSourceSnapshot(
                id=uuid4(),
                ingest_run_id=run.id,
                source_id=source.id,
                position=position,
                source_name=source.name,
                platform=source.platform,
                feed_url=source.feed_url,
                telegram_username=source.telegram_username,
                default_timezone=source.default_timezone or "UTC",
                etag=source.etag,
                last_modified=source.last_modified,
                status="queued",
            )
            for position, source in enumerate(members)
        ]
    )
    await session.flush()
    return run


class SourceCollectionLimitExceeded(ValueError):
    def __init__(self, *, collection_id: UUID, current_count: int, requested_additions: int) -> None:
        self.collection_id = collection_id
        self.current_count = current_count
        self.requested_additions = requested_additions
        super().__init__("A source collection can contain at most 100 sources.")
