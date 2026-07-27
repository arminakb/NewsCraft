from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    feed_url: Mapped[str | None] = mapped_column(Text)
    homepage_url: Mapped[str | None] = mapped_column(Text)
    telegram_username: Mapped[str | None] = mapped_column(Text)
    source_group: Mapped[str] = mapped_column(Text, nullable=False)
    language_hint: Mapped[str | None] = mapped_column(Text)
    default_timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="UTC")
    normalization_profile: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1440")
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_error_type: Mapped[str | None] = mapped_column(Text)
    last_error_message: Mapped[str | None] = mapped_column(Text)
    last_parse_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_suitable_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_media_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    health_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("platform", "feed_url", name="uq_sources_platform_feed_url"),
        UniqueConstraint("platform", "telegram_username", name="uq_sources_platform_telegram_username"),
        Index("ix_sources_next_fetch_at", "next_fetch_at"),
    )


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    started_at: Mapped[datetime] = timestamp_now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)


class RawPayload(Base):
    __tablename__ = "raw_payloads"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingest_runs.id"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    payload_kind: Mapped[str] = mapped_column(Text, nullable=False)
    request_url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    content_type: Mapped[str | None] = mapped_column(Text)
    body_sha256: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    parser_warnings: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    captured_at: Mapped[datetime] = timestamp_now()


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    canonical_url_hash: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    title_fingerprint: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_html_sanitized: Mapped[str | None] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(Text)
    script_code: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_raw: Mapped[str | None] = mapped_column(Text)
    date_source: Mapped[str | None] = mapped_column(Text)
    date_parse_status: Mapped[str] = mapped_column(Text, nullable=False)
    primary_source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    primary_image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    primary_media: Mapped[MediaAsset | None] = relationship(
        "MediaAsset",
        primaryjoin=lambda: foreign(ContentItem.primary_image_id) == MediaAsset.id,
        viewonly=True,
        uselist=False,
        lazy="selectin",
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="new")
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    content_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="article")
    content_type_confidence: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default="0")
    classification_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    classification_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    canonical_classification: Mapped[dict] = mapped_column(
        JSONB,
        Computed(
            "newscraft_canonical_article_classification("
            "content_type, metrics -> 'classification' ->> 'category', language_code)"
        ),
    )
    rewrite_bucket: Mapped[str | None] = mapped_column(Text)
    freshness_bucket: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    source_tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="needs_review")
    is_rewrite_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    rewrite_ready_reason: Mapped[str | None] = mapped_column(Text)
    rewrite_blockers: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    score_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    ranking_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    title_quality: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    title_was_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    content_intent: Mapped[str | None] = mapped_column(Text)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_items.id"))
    first_seen_at: Mapped[datetime] = timestamp_now()
    last_seen_at: Mapped[datetime] = timestamp_now()
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index(
            "ix_content_items_search",
            text("to_tsvector('simple'::regconfig, COALESCE(title, '') || ' ' || COALESCE(content_text, ''))"),
            postgresql_using="gin",
        ),
        Index(
            "ix_content_items_display_at",
            text("COALESCE(published_at, sort_at) DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_content_items_score_display_at",
            text("score DESC"),
            text("COALESCE(published_at, sort_at) DESC"),
            text("id DESC"),
        ),
    )


class ArticleCollection(Base):
    __tablename__ = "article_collections"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    items: Mapped[list[ArticleCollectionItem]] = relationship(
        "ArticleCollectionItem",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 60",
            name="ck_article_collections_name",
        ),
        UniqueConstraint(
            "normalized_name",
            name="uq_article_collections_normalized_name",
        ),
    )


class ArticleCollectionItem(Base):
    __tablename__ = "article_collection_items"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("article_collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    content_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    saved_at: Mapped[datetime] = timestamp_now()


class SourceItem(Base):
    __tablename__ = "source_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingest_runs.id"))
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_items.id"))
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("raw_payloads.id"))
    external_id_raw: Mapped[str | None] = mapped_column(Text)
    external_id_norm: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_url_norm: Mapped[str | None] = mapped_column(Text)
    canonical_url_candidate: Mapped[str | None] = mapped_column(Text)
    title_raw: Mapped[str | None] = mapped_column(Text)
    summary_raw: Mapped[str | None] = mapped_column(Text)
    content_html_raw: Mapped[str | None] = mapped_column(Text)
    content_text_raw: Mapped[str | None] = mapped_column(Text)
    author_raw: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    published_raw: Mapped[str | None] = mapped_column(Text)
    parser_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    first_seen_at: Mapped[datetime] = timestamp_now()
    last_seen_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index(
            "uq_source_item_external",
            "source_id",
            "external_id_norm",
            unique=True,
            postgresql_where=text("external_id_norm IS NOT NULL"),
        ),
        Index("ix_source_items_seen", "source_id", last_seen_at.desc()),
    )


class ItemIdentity(Base):
    __tablename__ = "item_identities"

    id: Mapped[uuid.UUID] = uuid_pk()
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_items.id"))
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_items.id"))
    identity_type: Mapped[str] = mapped_column(Text, nullable=False)
    identity_value: Mapped[str] = mapped_column(Text, nullable=False)
    identity_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"))
    confidence: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    is_strong: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index(
            "uq_identity_global_strong",
            "identity_type",
            "identity_hash",
            unique=True,
            postgresql_where=text("scope = 'global' AND is_strong"),
        ),
        Index(
            "uq_identity_source_strong",
            "source_id",
            "identity_type",
            "identity_hash",
            unique=True,
            postgresql_where=text("scope = 'source' AND is_strong"),
        ),
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric)
    byte_length: Mapped[int | None] = mapped_column(BigInteger)
    alt_text: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    source_field: Mapped[str] = mapped_column(Text, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(Text)
    storage_path: Mapped[str | None] = mapped_column(Text)
    fetch_status: Mapped[str] = mapped_column(Text, nullable=False)
    media_quality: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    media_confidence: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default="0")
    is_primary_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    media_source_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="external")
    asset_role: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    raw_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ItemMedia(Base):
    __tablename__ = "item_media"

    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"), primary_key=True)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("media_assets.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    confidence: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default="1.0")
    extracted_from: Mapped[str] = mapped_column(Text, nullable=False)


class RewriteCandidate(Base):
    __tablename__ = "rewrite_candidates"

    id: Mapped[uuid.UUID] = uuid_pk()
    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    bucket_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("content_item_id", "bucket_type", name="uq_rewrite_candidates_content_bucket"),
        Index("ix_rewrite_candidates_bucket_status", "bucket_type", "status", priority_score.desc()),
    )


class ContentDraft(Base):
    __tablename__ = "content_drafts"

    id: Mapped[uuid.UUID] = uuid_pk()
    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    human_notes: Mapped[str | None] = mapped_column(Text)
    draft_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_content_drafts_content_item", "content_item_id"),)
