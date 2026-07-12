from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
