from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk


class TelegramProxyProfile(Base):
    __tablename__ = "telegram_proxy_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    proxy_type: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"), nullable=True
    )
    password_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reachability_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("proxy_type IN ('http_connect', 'socks5')", name="ck_telegram_proxy_type"),
        CheckConstraint("port BETWEEN 1 AND 65535", name="ck_telegram_proxy_port"),
        CheckConstraint(
            "reachability_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
            name="ck_telegram_proxy_reachability",
        ),
        UniqueConstraint("name", name="uq_telegram_proxy_profiles_name"),
        UniqueConstraint("username_secret_id", name="uq_telegram_proxy_username_secret"),
        UniqueConstraint("password_secret_id", name="uq_telegram_proxy_password_secret"),
    )


class Destination(Base):
    __tablename__ = "destinations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    target_ref: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"), nullable=True
    )
    proxy_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telegram_proxy_profiles.id", ondelete="RESTRICT"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proxy_health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    telegram_health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    bot_health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    target_health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    administrator_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_bot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verified_bot_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verified_chat_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_chat_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    ownership: Mapped[str] = mapped_column(Text, nullable=False, server_default="operator_managed")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "target_type IS NULL OR target_type IN ('username', 'numeric_id', 'legacy')",
            name="ck_destination_target_type",
        ),
        CheckConstraint(
            "proxy_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy', 'direct')",
            name="ck_destination_proxy_health",
        ),
        CheckConstraint(
            "telegram_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
            name="ck_destination_telegram_health",
        ),
        CheckConstraint(
            "bot_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
            name="ck_destination_bot_health",
        ),
        CheckConstraint(
            "target_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
            name="ck_destination_target_health",
        ),
        CheckConstraint(
            "administrator_status IN ('unchecked', 'checking', 'administrator', 'not_administrator')",
            name="ck_destination_administrator_status",
        ),
        CheckConstraint(
            "ownership IN ('system_managed', 'operator_managed')",
            name="ck_destination_ownership",
        ),
        UniqueConstraint("platform", "target_ref", name="uq_destination_platform_target"),
        UniqueConstraint("platform", "canonical_target", name="uq_destination_platform_canonical_target"),
        UniqueConstraint("secret_id", name="uq_destination_secret_id"),
        Index("ix_destinations_proxy_profile_id", "proxy_profile_id"),
    )


class TelegramDestinationMigrationIssue(Base):
    """Durable operator follow-up created by the Telegram destination migration."""

    __tablename__ = "telegram_destination_migration_issues"

    destination_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("destinations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    issue_code: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = timestamp_now()


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
