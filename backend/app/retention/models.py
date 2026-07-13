from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk

RETENTION_POLICY_ID = "global"
RETENTION_SCHEMA_REVISION = "0009_operational_retention"
RETENTION_RUN_STATUSES = (
    "previewed",
    "queued",
    "running",
    "succeeded",
    "partial",
    "failed",
    "expired",
)


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        default=RETENTION_POLICY_ID,
        server_default=text("'global'"),
    )
    raw_payload_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default=text("30"),
    )
    completed_job_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=90,
        server_default=text("90"),
    )
    attempt_metadata_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=90,
        server_default=text("90"),
    )
    export_artifact_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=14,
        server_default=text("14"),
    )
    unreferenced_media_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default=text("30"),
    )
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 'global'", name="ck_retention_policy_singleton"),
        CheckConstraint(
            "raw_payload_days BETWEEN 7 AND 3650",
            name="ck_retention_policy_raw_payload_days",
        ),
        CheckConstraint(
            "completed_job_days BETWEEN 14 AND 3650",
            name="ck_retention_policy_completed_job_days",
        ),
        CheckConstraint(
            "attempt_metadata_days BETWEEN 14 AND 3650",
            name="ck_retention_policy_attempt_metadata_days",
        ),
        CheckConstraint(
            "export_artifact_days BETWEEN 1 AND 3650",
            name="ck_retention_policy_export_artifact_days",
        ),
        CheckConstraint(
            "unreferenced_media_days BETWEEN 7 AND 3650",
            name="ck_retention_policy_unreferenced_media_days",
        ),
    )


class RetentionRun(Base):
    __tablename__ = "retention_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    workflow_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_jobs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="previewed",
        server_default="previewed",
    )
    preview_token: Mapped[str] = mapped_column(Text, nullable=False)
    schema_revision: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=RETENTION_SCHEMA_REVISION,
        server_default=RETENTION_SCHEMA_REVISION,
    )
    policy_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    candidate_snapshot: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    cleanup_intent_snapshot: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    count_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_snapshot: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    previewed_at: Mapped[datetime] = timestamp_now()
    preview_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('previewed', 'queued', 'running', 'succeeded', 'partial', 'failed', 'expired')",
            name="ck_retention_run_status",
        ),
        CheckConstraint(
            "jsonb_typeof(policy_snapshot) = 'object'",
            name="ck_retention_run_policy_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(candidate_snapshot) = 'array'",
            name="ck_retention_run_candidate_snapshot_array",
        ),
        CheckConstraint(
            "jsonb_typeof(cleanup_intent_snapshot) = 'array'",
            name="ck_retention_run_cleanup_intent_snapshot_array",
        ),
        CheckConstraint(
            "jsonb_typeof(count_snapshot) = 'object'",
            name="ck_retention_run_count_snapshot_object",
        ),
        CheckConstraint(
            "jsonb_typeof(error_snapshot) = 'array'",
            name="ck_retention_run_error_snapshot_array",
        ),
        CheckConstraint(
            "preview_expires_at > previewed_at",
            name="ck_retention_run_preview_expiry",
        ),
        UniqueConstraint("preview_token", name="uq_retention_runs_preview_token"),
        UniqueConstraint("workflow_job_id", name="uq_retention_runs_workflow_job_id"),
        Index("ix_retention_runs_status_created", "status", created_at.desc(), id.desc()),
        Index(
            "ix_retention_runs_preview_expiry",
            "preview_expires_at",
            postgresql_where=text("status = 'previewed'"),
        ),
    )
