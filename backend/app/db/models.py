from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def timestamp_now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


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
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("platform", "feed_url", name="uq_sources_platform_feed_url"),
        UniqueConstraint("platform", "telegram_username", name="uq_sources_platform_telegram_username"),
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


class ContentProductionRequest(Base):
    __tablename__ = "content_production_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    topic: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default="telegram")
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="fa")
    tone: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str | None] = mapped_column(Text)
    max_candidates: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    require_rewrite_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    require_media: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="created")
    constraints_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_content_production_requests_status", "status", created_at.desc()),)


class CandidateShortlist(Base):
    __tablename__ = "candidate_shortlists"

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_requests.id"), nullable=False)
    selection_execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default="0")
    selection_reason_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    risk_flags_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source_snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    approval_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index("ix_candidate_shortlists_request_content_item", "request_id", "content_item_id"),
        Index("ix_candidate_shortlists_request_execution", "request_id", "selection_execution_id"),
        Index("ix_candidate_shortlists_request_rank", "request_id", "rank"),
        Index("ix_candidate_shortlists_approval_status", "approval_status"),
        UniqueConstraint(
            "selection_execution_id",
            "content_item_id",
            name="uq_candidate_shortlists_execution_content_item",
        ),
    )


class ContentProductionRun(Base):
    __tablename__ = "content_production_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_requests.id"), nullable=False)
    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default="telegram")
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="created")
    current_step: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_content_production_runs_request", "request_id"),
        Index("ix_content_production_runs_state_step", "state", "current_step"),
    )


class AgentStepRun(Base):
    __tablename__ = "agent_step_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_production_runs.id"))
    step_name: Mapped[str] = mapped_column(Text, nullable=False)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    input_snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    output_snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="started")
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = timestamp_now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str | None] = mapped_column(Text)
    token_usage_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        Index("ix_agent_step_runs_production_run", "production_run_id"),
        Index("ix_agent_step_runs_step_status", "step_name", "status"),
    )


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    event_id: Mapped[uuid.UUID] = uuid_pk()
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    causation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = timestamp_now()
    available_at: Mapped[datetime] = timestamp_now()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_workflow_events_status_available", "status", "available_at"),
        Index("ix_workflow_events_correlation", "correlation_id", "occurred_at"),
        Index("ix_workflow_events_aggregate", "aggregate_type", "aggregate_id", "occurred_at"),
    )


class ContentSufficiencyReport(Base):
    __tablename__ = "content_sufficiency_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_production_runs.id"))
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_items.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default="0")
    reasons_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    allowed_next_step: Mapped[str | None] = mapped_column(Text)
    blocked_steps_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    minimum_needed_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    input_snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index("ix_content_sufficiency_reports_run_created", "production_run_id", created_at.desc()),
        Index("ix_content_sufficiency_reports_item_created", "content_item_id", created_at.desc()),
        Index("ix_content_sufficiency_reports_status", "status"),
    )


class ArticleExtractionResult(Base):
    __tablename__ = "article_extraction_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_url: Mapped[str | None] = mapped_column(Text)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index("ix_article_extraction_results_run_created", "production_run_id", created_at.desc()),
        Index("ix_article_extraction_results_status", "status"),
    )


class WebEnrichmentResult(Base):
    __tablename__ = "web_enrichment_results"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    content_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    query_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    findings_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source_attribution_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index("ix_web_enrichment_results_run_created", "production_run_id", created_at.desc()),
        Index("ix_web_enrichment_results_status", "status"),
    )


class EditorialBrief(Base):
    __tablename__ = "editorial_briefs"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    angle: Mapped[str] = mapped_column(Text, nullable=False)
    key_facts_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source_claims_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    unsafe_or_unverified_claims_json: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    audience: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str | None] = mapped_column(Text)
    do_not_say_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    evidence_ids_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    generation_metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index("ix_editorial_briefs_production_run_created", "production_run_id", created_at.desc()),
    )


class TelegramDraft(Base):
    __tablename__ = "telegram_drafts"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    brief_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("editorial_briefs.id"), nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    hashtags_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source_links_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    evidence_ids_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    generation_metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_telegram_drafts_production_run_created", "production_run_id", created_at.desc()),
        Index("ix_telegram_drafts_status", "status"),
    )


class DraftQualityReport(Base):
    __tablename__ = "draft_quality_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("telegram_drafts.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric, nullable=False, server_default="0")
    factuality_warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    unsupported_claims_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    style_warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    required_revisions_json: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    rubric_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    evaluation_metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        Index("ix_draft_quality_reports_run_created", "production_run_id", created_at.desc()),
        Index("ix_draft_quality_reports_draft", "draft_id"),
        Index("ix_draft_quality_reports_status", "status"),
    )


class VisualBrief(Base):
    __tablename__ = "visual_briefs"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    selected_media_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_assets.id"))
    needs_generation: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    visual_prompt: Mapped[str | None] = mapped_column(Text)
    visual_style: Mapped[str | None] = mapped_column(Text)
    provider_name: Mapped[str | None] = mapped_column(Text)
    provider_request_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    provider_result_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_visual_briefs_production_run_created", "production_run_id", created_at.desc()),
        Index("ix_visual_briefs_status", "status"),
    )


class TelegramPostPackage(Base):
    __tablename__ = "telegram_post_packages"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("telegram_drafts.id"), nullable=False)
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_assets.id"))
    image_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("visual_briefs.id"))
    package_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    approval_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_telegram_post_packages_run_created", "production_run_id", created_at.desc()),
        Index("ix_telegram_post_packages_approval_status", "approval_status"),
    )


class TelegramDispatchRequest(Base):
    __tablename__ = "telegram_dispatch_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    production_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_production_runs.id"), nullable=False)
    package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("telegram_post_packages.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    dispatch_payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_telegram_dispatch_requests_run_created", "production_run_id", created_at.desc()),
        Index("ix_telegram_dispatch_requests_package", "package_id"),
        Index("ix_telegram_dispatch_requests_status", "status"),
    )
