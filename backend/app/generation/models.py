from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base, timestamp_now, uuid_pk
from app.workflows.states import ContentPackState, GenerationRunState, VariantApprovalState


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    output_language: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(Text, nullable=False)
    editorial_rules: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    attribution_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    default_hashtags: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    platform_preferences: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_brand_profiles_name"),
        Index(
            "uq_brand_profiles_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = uuid_pk()
    purpose_key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("purpose_key", name="uq_prompt_templates_purpose_key"),)


class PromptTemplateVersion(Base):
    __tablename__ = "prompt_template_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    prompt_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_templates.id"), nullable=False
    )
    prompt_template: Mapped[PromptTemplate] = relationship()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_template: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    checksum_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_by_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_by_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    activation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        UniqueConstraint("prompt_template_id", "version", name="uq_prompt_template_version"),
        Index(
            "uq_prompt_template_versions_one_active",
            "prompt_template_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        CheckConstraint(
            "NOT is_active OR (activated_at IS NOT NULL AND activated_by_type IS NOT NULL "
            "AND activated_by_id IS NOT NULL AND activation_reason IS NOT NULL)",
            name="ck_prompt_template_versions_active_metadata",
        ),
    )


class AIProviderProfile(Base):
    __tablename__ = "ai_provider_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    default_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("name", name="uq_ai_provider_profiles_name"),)


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    story_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_revisions.id"), nullable=True
    )
    provider_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_provider_profiles.id"), nullable=True
    )
    prompt_template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_template_versions.id"), nullable=False
    )
    requested_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[GenerationRunState] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    output_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'completed', 'failed')",
            name="ck_generation_runs_status",
        ),
        Index("ix_generation_runs_status_created", "status", created_at.desc()),
    )


class GenerationAttempt(Base):
    __tablename__ = "generation_attempts"

    id: Mapped[uuid.UUID] = uuid_pk()
    generation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_runs.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    requested_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    response_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    validation_errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("generation_run_id", "attempt_number", name="uq_generation_attempt_number"),)


class ContentPack(Base):
    __tablename__ = "content_packs"

    id: Mapped[uuid.UUID] = uuid_pk()
    story_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("story_revisions.id"), nullable=False
    )
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id"), nullable=False
    )
    status: Mapped[ContentPackState] = mapped_column(Text, nullable=False, server_default="draft")
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'ready')", name="ck_content_packs_status"),
        UniqueConstraint("story_revision_id", "brand_profile_id", name="uq_content_pack_story_brand"),
    )


class PlatformVariant(Base):
    __tablename__ = "platform_variants"

    id: Mapped[uuid.UUID] = uuid_pk()
    content_pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_packs.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (UniqueConstraint("content_pack_id", "platform", name="uq_platform_variant_platform"),)


class PlatformVariantRevision(Base):
    __tablename__ = "platform_variant_revisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    platform_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_variants.id"), nullable=False
    )
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_variant_revisions.id"), nullable=True
    )
    generation_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_attempts.id"), nullable=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_map: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    validation_results: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    approval_state: Mapped[VariantApprovalState] = mapped_column(Text, nullable=False, server_default="draft")
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint(
            "approval_state IN ('draft', 'pending_review', 'approved', 'rejected')",
            name="ck_platform_variant_revision_approval_state",
        ),
        UniqueConstraint(
            "platform_variant_id",
            "revision_number",
            name="uq_platform_variant_revision_number",
        ),
    )
