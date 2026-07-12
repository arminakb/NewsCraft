from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk


class Destination(Base):
    __tablename__ = "destinations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    target_ref: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("platform", "target_ref", name="uq_destination_platform_target"),)


class PublishJob(Base):
    __tablename__ = "publish_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_jobs.id"), nullable=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("destinations.id"), nullable=False)
    platform_variant_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_variant_revisions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_publish_jobs_idempotency_key"),
        Index("ix_publish_jobs_status_scheduled", "status", "scheduled_for"),
        Index("ix_publish_jobs_workflow_job_id", "workflow_job_id"),
    )


class PublishAttempt(Base):
    __tablename__ = "publish_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    publish_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("publish_jobs.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sanitized_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_response: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("publish_job_id", "attempt_number", name="uq_publish_attempt_number"),)


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = uuid_pk()
    publish_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("publish_jobs.id"), nullable=False)
    destination_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("destinations.id"), nullable=False)
    platform_variant_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_variant_revisions.id"), nullable=False
    )
    remote_message_ids: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reconciliation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="confirmed")

    __table_args__ = (
        UniqueConstraint("publish_job_id", name="uq_publications_publish_job_id"),
        UniqueConstraint(
            "destination_id",
            "platform_variant_revision_id",
            name="uq_publication_destination_variant_revision",
        ),
        Index("ix_publications_published_at", published_at.desc()),
    )


class PublishOperationReceipt(Base):
    __tablename__ = "publish_operation_receipts"

    id: Mapped[uuid.UUID] = uuid_pk()
    publish_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publish_jobs.id", ondelete="CASCADE"), nullable=False
    )
    operation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_key: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    remote_message_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default=text("'{}'::bigint[]")
    )
    response_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ambiguous_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("publish_job_id", "operation_key", name="uq_publish_operation_job_key"),
        UniqueConstraint("publish_job_id", "operation_index", name="uq_publish_operation_job_index"),
        Index("ix_publish_operation_retry", "status", "next_attempt_at"),
    )
