from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk

MANUAL_PLATFORMS = ("instagram", "x", "blog")
MANUAL_PLAN_STATUSES = ("planned", "ready", "manual_published", "cancelled")

CHECKLIST_IDS_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    "instagram": (
        "copy_reviewed",
        "citations_verified",
        "media_and_alt_text_ready",
        "platform_requirements_rechecked",
    ),
    "x": (
        "thread_order_reviewed",
        "citations_and_links_verified",
        "media_and_alt_text_ready",
        "platform_requirements_rechecked",
    ),
    "blog": (
        "article_reviewed",
        "citations_and_links_verified",
        "seo_fields_reviewed",
        "media_and_alt_text_ready",
    ),
}


def _checklist_shape_branch(platform: str, keys: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{key}'" for key in keys)
    required = " AND ".join(f"checklist_state ? '{key}'" for key in keys)
    boolean_values = " AND ".join(f"jsonb_typeof(checklist_state -> '{key}') = 'boolean'" for key in keys)
    return (
        f"WHEN '{platform}' THEN ({required}) "
        f"AND checklist_state - ARRAY[{quoted}]::text[] = '{{}}'::jsonb "
        f"AND ({boolean_values})"
    )


def _ready_branch(platform: str, keys: tuple[str, ...]) -> str:
    complete = " AND ".join(f"checklist_state -> '{key}' = 'true'::jsonb" for key in keys)
    return f"WHEN '{platform}' THEN ({complete})"


CHECKLIST_SHAPE_CONSTRAINT = (
    "CASE platform "
    + " ".join(_checklist_shape_branch(platform, keys) for platform, keys in CHECKLIST_IDS_BY_PLATFORM.items())
    + " ELSE false END"
)

READY_CHECKLIST_CONSTRAINT = (
    "status = 'cancelled' OR ((status IN ('ready', 'manual_published')) = (CASE platform "
    + " ".join(_ready_branch(platform, keys) for platform, keys in CHECKLIST_IDS_BY_PLATFORM.items())
    + " ELSE false END))"
)


class ManualPublicationPlan(Base):
    __tablename__ = "manual_publication_plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    platform_variant_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_variant_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    display_timezone: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'Asia/Tehran'"),
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="planned")
    checklist_state: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "platform IN ('instagram', 'x', 'blog')",
            name="ck_manual_publication_platform",
        ),
        CheckConstraint(
            "status IN ('planned', 'ready', 'manual_published', 'cancelled')",
            name="ck_manual_publication_status",
        ),
        CheckConstraint(
            "jsonb_typeof(checklist_state) = 'object'",
            name="ck_manual_publication_checklist_object",
        ),
        CheckConstraint(
            CHECKLIST_SHAPE_CONSTRAINT,
            name="ck_manual_publication_checklist_shape",
        ),
        CheckConstraint(
            READY_CHECKLIST_CONSTRAINT,
            name="ck_manual_publication_ready_checklist",
        ),
        CheckConstraint(
            "(status = 'manual_published' AND completed_at IS NOT NULL) OR "
            "(status <> 'manual_published' AND completed_at IS NULL "
            "AND external_url IS NULL AND operator_note IS NULL)",
            name="ck_manual_publication_completion",
        ),
        Index(
            "uq_manual_publication_active_revision",
            "platform_variant_revision_id",
            unique=True,
            postgresql_where=text("status IN ('planned', 'ready')"),
        ),
        Index(
            "ix_manual_publication_schedule",
            "scheduled_for",
            "id",
        ),
        Index(
            "ix_manual_publication_history",
            completed_at.desc(),
            id.desc(),
            postgresql_where=text("status = 'manual_published'"),
        ),
    )
