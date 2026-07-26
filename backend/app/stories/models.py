from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk
from app.stories.states import INBOX


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=INBOX)
    primary_language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id"), nullable=True
    )
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('inbox', 'shortlisted', 'rejected', 'drafted', 'telegram_provisional')",
            name="ck_stories_status",
        ),
        Index(
            "ix_stories_active_updated",
            "status",
            updated_at.desc(),
            postgresql_where=superseded_by_id.is_(None),
        ),
    )


class StoryEvidenceSnapshot(Base):
    __tablename__ = "story_evidence_snapshots"

    id: Mapped[uuid.UUID] = uuid_pk()
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False)
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id"), nullable=True
    )
    evidence_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    captured_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (UniqueConstraint("story_id", "evidence_key", name="uq_story_evidence_key"),)


class StoryRevision(Base):
    __tablename__ = "story_revisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_revisions.id"), nullable=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    facts: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    disagreements: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    angles: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        UniqueConstraint("story_id", "revision_number", name="uq_story_revision_number"),
        Index("ix_story_revisions_story_created", "story_id", created_at.desc()),
    )


class StoryEvidenceLink(Base):
    __tablename__ = "story_evidence_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    story_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_revisions.id"), nullable=False
    )
    evidence_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_evidence_snapshots.id"), nullable=False
    )
    claim_key: Mapped[str] = mapped_column(Text, nullable=False)
    relationship: Mapped[str] = mapped_column(Text, nullable=False, server_default="supports")
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        UniqueConstraint(
            "story_revision_id",
            "evidence_snapshot_id",
            "claim_key",
            name="uq_story_evidence_link_claim",
        ),
    )
