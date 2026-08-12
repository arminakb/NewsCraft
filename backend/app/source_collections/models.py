from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk

SOURCE_COLLECTION_MAX_SIZE = 100
CONTINUOUS_SUBSCRIPTION_ACTIVE_STATUSES = ("starting", "running", "stopping")
CONTINUOUS_SUBSCRIPTION_STATUSES = (*CONTINUOUS_SUBSCRIPTION_ACTIVE_STATUSES, "stopped", "error")


class SourceCollection(Base):
    __tablename__ = "source_collections"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    memberships: Mapped[list[SourceCollectionMembership]] = relationship(
        "SourceCollectionMembership",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 60",
            name="ck_source_collections_name",
        ),
        UniqueConstraint("normalized_name", name="uq_source_collections_normalized_name"),
        Index("ix_source_collections_name_lookup", "normalized_name", "id"),
    )


class SourceCollectionIngestionSubscription(Base):
    """Durable lifecycle for repeated Source Collection ingestion cycles."""

    __tablename__ = "source_collection_ingestion_subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_collection_name_at_start: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="continuous")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="starting")
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cycle_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="operator")
    last_cycle_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_cycle_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_cycle_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_source_collection_ingestion_subscriptions_idempotency"),
        CheckConstraint("mode = 'continuous'", name="ck_source_collection_ingestion_subscription_mode"),
        CheckConstraint(
            "status IN ('starting', 'running', 'stopping', 'stopped', 'error')",
            name="ck_source_collection_ingestion_subscription_status",
        ),
        CheckConstraint("interval_minutes BETWEEN 1 AND 1440", name="ck_source_collection_ingestion_interval"),
        CheckConstraint("cycle_count >= 0", name="ck_source_collection_ingestion_cycle_count"),
        Index(
            "uq_source_collection_ingestion_subscription_active",
            "source_collection_id",
            unique=True,
            postgresql_where=text(
                "source_collection_id IS NOT NULL AND status IN ('starting', 'running', 'stopping')"
            ),
        ),
        Index(
            "ix_source_collection_ingestion_subscription_due",
            "status",
            "next_cycle_at",
        ),
        Index(
            "ix_source_collection_ingestion_subscription_collection",
            "source_collection_id",
            "created_at",
        ),
    )


class SourceCollectionMembership(Base):
    __tablename__ = "source_collection_memberships"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index(
            "ix_source_collection_memberships_collection_source",
            "collection_id",
            "source_id",
        ),
        Index(
            "ix_source_collection_memberships_source_collection",
            "source_id",
            "collection_id",
        ),
    )


class IngestRunSourceSnapshot(Base):
    """Immutable source input captured for one collection ingest run."""

    __tablename__ = "ingest_run_source_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    feed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        UniqueConstraint("ingest_run_id", "source_id", name="uq_ingest_run_source_snapshot_source"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')",
            name="ck_ingest_run_source_snapshot_status",
        ),
        Index("ix_ingest_run_source_snapshots_run_status", "ingest_run_id", "status"),
        Index("ix_ingest_run_source_snapshots_source", "source_id", "ingest_run_id"),
    )
