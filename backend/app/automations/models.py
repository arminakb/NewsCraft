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
    Sequence,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk


class AutomationRoute(Base):
    __tablename__ = "automation_routes"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    destination_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("destinations.id"), nullable=False)
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id"), nullable=False
    )
    prompt_template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_template_versions.id"), nullable=False
    )
    ai_provider_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_provider_profiles.id"), nullable=False
    )
    access_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="public_html")
    research_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="off")
    content_filters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    media_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default="preserve")
    attribution_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default="preserve")
    custom_footer: Mapped[str | None] = mapped_column(Text, nullable=True)
    publishing_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default="review_required")
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    quiet_hours: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    retry_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    cursor_state: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    backfill_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backfill_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_automation_routes_enabled_next_poll", "enabled", "next_poll_at"),)


class TelegramSourceConfig(Base):
    __tablename__ = "telegram_source_configs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    access_mode: Mapped[str] = mapped_column(Text, nullable=False)
    channel_ref: Mapped[str] = mapped_column(Text, nullable=False)
    peer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_id_secret_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_hash_secret_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_secret_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("access_mode IN ('public_html', 'mtproto_user')", name="ck_telegram_source_access_mode"),
        CheckConstraint(
            "(access_mode = 'public_html' AND api_id_secret_ref IS NULL AND api_hash_secret_ref IS NULL "
            "AND session_secret_ref IS NULL) OR "
            "(access_mode = 'mtproto_user' AND api_id_secret_ref IS NOT NULL AND api_hash_secret_ref IS NOT NULL "
            "AND session_secret_ref IS NOT NULL)",
            name="ck_telegram_source_secret_mode",
        ),
        UniqueConstraint("access_mode", "channel_ref", name="uq_telegram_source_mode_channel"),
    )


dispatch_creation_sequence = Sequence("automation_dispatch_creation_sequence_seq")


class AutomationDispatch(Base):
    __tablename__ = "automation_dispatches"

    id: Mapped[uuid.UUID] = uuid_pk()
    creation_sequence: Mapped[int] = mapped_column(
        BigInteger,
        dispatch_creation_sequence,
        server_default=dispatch_creation_sequence.next_value(),
        nullable=False,
        unique=True,
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automation_routes.id", ondelete="CASCADE"), nullable=False
    )
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=False
    )
    story_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    dispatch_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="captured")
    generation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_runs.id"), nullable=True
    )
    variant_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_variant_revisions.id"), nullable=True
    )
    publish_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publish_jobs.id"), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("route_id", "source_key", name="uq_automation_dispatch_route_source"),
        CheckConstraint(
            "dispatch_kind IN ('live', 'backfill', 'dry_run', 'source_edit')",
            name="ck_automation_dispatch_kind",
        ),
        Index("ix_automation_dispatch_route_created", "route_id", created_at.desc()),
        Index("ix_automation_dispatch_route_sequence", "route_id", creation_sequence.desc()),
    )
