from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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


class Automation(Base):
    __tablename__ = "automations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle: Mapped[str] = mapped_column(Text, nullable=False, server_default="inactive")
    owner_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="operator_managed")
    owner_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="local-owner")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    draft_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    activation_idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('inactive', 'active', 'paused', 'archived')",
            name="ck_automations_lifecycle",
        ),
        CheckConstraint(
            "owner_type IN ('system_managed', 'operator_managed', 'legacy_migrated')",
            name="ck_automations_owner_type",
        ),
        CheckConstraint("revision >= 1", name="ck_automations_revision"),
        CheckConstraint(
            "(lifecycle = 'archived') = (archived_at IS NOT NULL)",
            name="ck_automations_archived_state",
        ),
        ForeignKeyConstraint(
            ["id", "active_version_id"],
            ["automation_versions.automation_id", "automation_versions.id"],
            name="fk_automations_active_version",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["id", "draft_version_id"],
            ["automation_versions.automation_id", "automation_versions.id"],
            name="fk_automations_draft_version",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        UniqueConstraint("idempotency_key", name="uq_automations_idempotency_key"),
        Index("ix_automations_lifecycle_updated", "lifecycle", updated_at.desc()),
    )


class AutomationVersion(Base):
    __tablename__ = "automation_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automations.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False)
    graph_hash: Mapped[str] = mapped_column(Text, nullable=False)
    compiler_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiled_plan: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    validation_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    creation_actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    creation_actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    creation_reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_automation_versions_version"),
        CheckConstraint("schema_version = 1", name="ck_automation_versions_schema_version"),
        CheckConstraint("char_length(graph_hash) = 64", name="ck_automation_versions_graph_hash"),
        UniqueConstraint("automation_id", "id", name="uq_automation_versions_automation_id"),
        UniqueConstraint("automation_id", "version", name="uq_automation_versions_number"),
        UniqueConstraint("automation_id", "idempotency_key", name="uq_automation_versions_idempotency"),
        Index("ix_automation_versions_automation_created", "automation_id", created_at.desc()),
        Index("ix_automation_versions_automation_graph_hash", "automation_id", "graph_hash"),
    )


class AutomationRuntimeProjection(Base):
    __tablename__ = "automation_runtime_projections"

    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automations.id", ondelete="CASCADE"), primary_key=True
    )
    automation_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automation_routes.id", ondelete="RESTRICT"), nullable=False
    )
    projection_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="telegram_route")
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "projection_type IN ('telegram_route')",
            name="ck_automation_runtime_projections_type",
        ),
        ForeignKeyConstraint(
            ["automation_id", "automation_version_id"],
            ["automation_versions.automation_id", "automation_versions.id"],
            name="fk_automation_runtime_projections_owned_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("route_id", name="uq_automation_runtime_projections_route_id"),
        Index("ix_automation_runtime_projections_version", "automation_version_id"),
    )


class AutomationTemplate(Base):
    __tablename__ = "automation_templates"

    id: Mapped[uuid.UUID] = uuid_pk()
    seed_key: Mapped[str] = mapped_column(Text, nullable=False)
    seed_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ownership: Mapped[str] = mapped_column(Text, nullable=False, server_default="system_managed")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    complexity: Mapped[str] = mapped_column(Text, nullable=False)
    graph_seed: Mapped[dict] = mapped_column(JSONB, nullable=False)
    capability_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("seed_version >= 1", name="ck_automation_templates_seed_version"),
        CheckConstraint(
            "ownership IN ('system_managed', 'operator_managed')",
            name="ck_automation_templates_ownership",
        ),
        CheckConstraint(
            "complexity IN ('starter', 'intermediate', 'advanced')",
            name="ck_automation_templates_complexity",
        ),
        UniqueConstraint("seed_key", "seed_version", name="uq_automation_templates_seed_version"),
        Index("ix_automation_templates_active", "seed_key", postgresql_where=text("archived_at IS NULL")),
    )


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automations.id", ondelete="RESTRICT"), nullable=False
    )
    automation_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    root_workflow_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_jobs.id", ondelete="SET NULL"), nullable=True
    )
    trigger_kind: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    current_node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        # Keep the retired discriminator so historical runs remain readable; it is not a current workflow node type.
        CheckConstraint(
            "trigger_kind IN ('manual', 'schedule', 'telegram_new_item', 'collection_article_added', "
            "'new_source_item', 'legacy')",
            name="ck_automation_runs_trigger_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'waiting_for_review', 'succeeded', 'warning', "
            "'failed', 'cancelled')",
            name="ck_automation_runs_status",
        ),
        ForeignKeyConstraint(
            ["automation_id", "automation_version_id"],
            ["automation_versions.automation_id", "automation_versions.id"],
            name="fk_automation_runs_owned_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("root_workflow_job_id", name="uq_automation_runs_root_workflow_job_id"),
        UniqueConstraint("idempotency_key", name="uq_automation_runs_idempotency_key"),
        CheckConstraint("char_length(request_hash) = 64", name="ck_automation_runs_request_hash"),
        Index("ix_automation_runs_automation_created", "automation_id", created_at.desc()),
        Index("ix_automation_runs_status_created", "status", created_at.desc()),
        Index("ix_automation_runs_version", "automation_version_id"),
        Index("ix_automation_runs_dry_run_created", "dry_run", created_at.desc()),
    )


class AutomationNodeRun(Base):
    __tablename__ = "automation_node_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    automation_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automation_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    workflow_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_jobs.id", ondelete="SET NULL"), nullable=True
    )
    automation_dispatch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("automation_dispatches.id", ondelete="SET NULL"), nullable=True
    )
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True
    )
    generation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True
    )
    platform_variant_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_variant_revisions.id", ondelete="SET NULL"), nullable=True
    )
    publish_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publish_jobs.id", ondelete="SET NULL"), nullable=True
    )
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id", ondelete="SET NULL"), nullable=True
    )
    input_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    output_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    usage: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    retry_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    safe_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = timestamp_now()

    __table_args__ = (
        CheckConstraint("attempt >= 1", name="ck_automation_node_runs_attempt"),
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'succeeded', 'warning', 'failed', 'skipped', "
            "'waiting_for_review')",
            name="ck_automation_node_runs_status",
        ),
        UniqueConstraint(
            "automation_run_id",
            "node_id",
            "attempt",
            name="uq_automation_node_runs_attempt",
        ),
        Index("ix_automation_node_runs_run_status", "automation_run_id", "status"),
        Index("ix_automation_node_runs_workflow_job", "workflow_job_id"),
        Index("ix_automation_node_runs_dispatch", "automation_dispatch_id"),
        Index("ix_automation_node_runs_research", "research_run_id"),
        Index("ix_automation_node_runs_generation", "generation_run_id"),
        Index("ix_automation_node_runs_revision", "platform_variant_revision_id"),
        Index("ix_automation_node_runs_publish_job", "publish_job_id"),
        Index("ix_automation_node_runs_publication", "publication_id"),
    )
