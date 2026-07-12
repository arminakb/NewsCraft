"""add content platform domain spine

Revision ID: 0004_platform_spine
Revises: 0003_content_intelligence_schema
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_platform_spine"
down_revision = "0003_content_intelligence_schema"
branch_labels = None
depends_on = None


def _uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _json_object_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


def _json_array_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'[]'::jsonb"),
        nullable=False,
    )


def _created_at_column(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "stories",
        _uuid_column("id"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("primary_language", sa.Text(), server_default="en", nullable=False),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["stories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stories_active_updated",
        "stories",
        ["status", sa.text("updated_at DESC")],
        postgresql_where=sa.text("superseded_by_id IS NULL"),
    )

    op.create_table(
        "story_evidence_snapshots",
        _uuid_column("id"),
        _uuid_column("story_id"),
        _uuid_column("content_item_id", nullable=True),
        sa.Column("evidence_key", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=False),
        _json_array_column("authors"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        _json_object_column("snapshot_metadata"),
        _created_at_column("captured_at"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "evidence_key", name="uq_story_evidence_key"),
    )

    op.create_table(
        "story_revisions",
        _uuid_column("id"),
        _uuid_column("story_id"),
        _uuid_column("parent_revision_id", nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        _json_array_column("facts"),
        _json_array_column("disagreements"),
        _json_array_column("angles"),
        _json_array_column("citations"),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created_at_column(),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["story_revisions.id"]),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_id", "revision_number", name="uq_story_revision_number"),
    )
    op.create_index(
        "ix_story_revisions_story_created",
        "story_revisions",
        ["story_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "story_evidence_links",
        _uuid_column("id"),
        _uuid_column("story_revision_id"),
        _uuid_column("evidence_snapshot_id"),
        sa.Column("claim_key", sa.Text(), nullable=False),
        sa.Column("relationship", sa.Text(), server_default="supports", nullable=False),
        _created_at_column(),
        sa.ForeignKeyConstraint(["evidence_snapshot_id"], ["story_evidence_snapshots.id"]),
        sa.ForeignKeyConstraint(["story_revision_id"], ["story_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "story_revision_id",
            "evidence_snapshot_id",
            "claim_key",
            name="uq_story_evidence_link_claim",
        ),
    )

    op.create_table(
        "brand_profiles",
        _uuid_column("id"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("output_language", sa.Text(), nullable=False),
        sa.Column("tone", sa.Text(), nullable=False),
        _json_array_column("editorial_rules"),
        _json_object_column("attribution_rules"),
        _json_array_column("default_hashtags"),
        _json_object_column("platform_preferences"),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_brand_profiles_name"),
    )

    op.create_table(
        "prompt_templates",
        _uuid_column("id"),
        sa.Column("purpose_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purpose_key", name="uq_prompt_templates_purpose_key"),
    )

    op.create_table(
        "prompt_template_versions",
        _uuid_column("id"),
        _uuid_column("prompt_template_id"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_template", sa.Text(), nullable=False),
        sa.Column("user_template", sa.Text(), nullable=False),
        sa.Column("output_schema_version", sa.Text(), nullable=False),
        _json_object_column("output_schema"),
        sa.Column("checksum_sha256", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        _created_at_column(),
        sa.ForeignKeyConstraint(["prompt_template_id"], ["prompt_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_template_id", "version", name="uq_prompt_template_version"),
    )

    op.create_table(
        "ai_provider_profiles",
        _uuid_column("id"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("default_model", sa.Text(), nullable=True),
        sa.Column("secret_ref", sa.Text(), nullable=True),
        _json_object_column("settings"),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_ai_provider_profiles_name"),
    )

    op.create_table(
        "research_runs",
        _uuid_column("id"),
        _uuid_column("story_id"),
        sa.Column("requested_mode", sa.Text(), nullable=False),
        _uuid_column("provider_profile_id", nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("query_budget", sa.Integer(), server_default="0", nullable=False),
        sa.Column("page_budget", sa.Integer(), server_default="0", nullable=False),
        sa.Column("time_budget_seconds", sa.Integer(), server_default="0", nullable=False),
        _uuid_column("result_story_revision_id", nullable=True),
        _created_at_column(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["ai_provider_profiles.id"]),
        sa.ForeignKeyConstraint(["result_story_revision_id"], ["story_revisions.id"]),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "research_attempts",
        _uuid_column("id"),
        _uuid_column("research_run_id"),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        _json_array_column("queries"),
        sa.Column("status", sa.Text(), nullable=False),
        _json_object_column("usage"),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("research_run_id", "attempt_number", name="uq_research_attempt_number"),
    )

    op.create_table(
        "research_sources",
        _uuid_column("id"),
        _uuid_column("research_run_id"),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_sha256", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.Text(), nullable=False),
        sa.Column("relevance", sa.Numeric(), server_default="0", nullable=False),
        sa.Column("citation_key", sa.Text(), nullable=False),
        _json_object_column("snapshot_metadata"),
        _created_at_column(),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("research_run_id", "url", name="uq_research_source_url"),
    )

    op.create_table(
        "generation_runs",
        _uuid_column("id"),
        _uuid_column("story_revision_id", nullable=True),
        _uuid_column("provider_profile_id", nullable=True),
        _uuid_column("prompt_template_version_id"),
        sa.Column("requested_model", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        _json_object_column("request_payload"),
        _json_object_column("output_payload"),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        sa.ForeignKeyConstraint(["prompt_template_version_id"], ["prompt_template_versions.id"]),
        sa.ForeignKeyConstraint(["provider_profile_id"], ["ai_provider_profiles.id"]),
        sa.ForeignKeyConstraint(["story_revision_id"], ["story_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_generation_runs_status_created",
        "generation_runs",
        ["status", sa.text("created_at DESC")],
    )

    op.create_table(
        "generation_attempts",
        _uuid_column("id"),
        _uuid_column("generation_run_id"),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("requested_model", sa.Text(), nullable=True),
        sa.Column("resolved_model", sa.Text(), nullable=True),
        _json_object_column("prompt_snapshot"),
        _json_object_column("response_payload"),
        _json_object_column("usage"),
        _json_array_column("validation_errors"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_run_id", "attempt_number", name="uq_generation_attempt_number"),
    )

    op.create_table(
        "content_packs",
        _uuid_column("id"),
        _uuid_column("story_revision_id"),
        _uuid_column("brand_profile_id"),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.ForeignKeyConstraint(["brand_profile_id"], ["brand_profiles.id"]),
        sa.ForeignKeyConstraint(["story_revision_id"], ["story_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("story_revision_id", "brand_profile_id", name="uq_content_pack_story_brand"),
    )

    op.create_table(
        "platform_variants",
        _uuid_column("id"),
        _uuid_column("content_pack_id"),
        sa.Column("platform", sa.Text(), nullable=False),
        _created_at_column(),
        sa.ForeignKeyConstraint(["content_pack_id"], ["content_packs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_pack_id", "platform", name="uq_platform_variant_platform"),
    )

    op.create_table(
        "platform_variant_revisions",
        _uuid_column("id"),
        _uuid_column("platform_variant_id"),
        _uuid_column("parent_revision_id", nullable=True),
        _uuid_column("generation_attempt_id", nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        _json_object_column("content"),
        sa.Column("content_hash", sa.Text(), nullable=False),
        _json_array_column("evidence_map"),
        _json_array_column("validation_results"),
        sa.Column("approval_state", sa.Text(), server_default="draft", nullable=False),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        _created_at_column(),
        sa.CheckConstraint(
            "approval_state IN ('draft', 'pending_review', 'approved', 'rejected')",
            name="ck_platform_variant_revision_approval_state",
        ),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"]),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["platform_variant_revisions.id"]),
        sa.ForeignKeyConstraint(["platform_variant_id"], ["platform_variants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_variant_id",
            "revision_number",
            name="uq_platform_variant_revision_number",
        ),
    )

    op.create_table(
        "destinations",
        _uuid_column("id"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("target_ref", sa.Text(), nullable=False),
        sa.Column("secret_ref", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("health_status", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        _json_object_column("settings"),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "target_ref", name="uq_destination_platform_target"),
    )

    op.create_table(
        "automation_routes",
        _uuid_column("id"),
        sa.Column("name", sa.Text(), nullable=False),
        _uuid_column("source_id"),
        _uuid_column("destination_id"),
        _uuid_column("brand_profile_id"),
        _uuid_column("prompt_template_version_id"),
        _uuid_column("ai_provider_profile_id"),
        sa.Column("access_mode", sa.Text(), server_default="public_html", nullable=False),
        sa.Column("research_mode", sa.Text(), server_default="off", nullable=False),
        _json_object_column("content_filters"),
        sa.Column("media_policy", sa.Text(), server_default="preserve", nullable=False),
        sa.Column("attribution_policy", sa.Text(), server_default="preserve", nullable=False),
        sa.Column("custom_footer", sa.Text(), nullable=True),
        sa.Column("publishing_policy", sa.Text(), server_default="review_required", nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), server_default="300", nullable=False),
        _json_object_column("quiet_hours"),
        _json_object_column("retry_policy"),
        _json_object_column("cursor_state"),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backfill_limit", sa.Integer(), nullable=True),
        sa.Column("backfill_since", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.ForeignKeyConstraint(["ai_provider_profile_id"], ["ai_provider_profiles.id"]),
        sa.ForeignKeyConstraint(["brand_profile_id"], ["brand_profiles.id"]),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"]),
        sa.ForeignKeyConstraint(["prompt_template_version_id"], ["prompt_template_versions.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_automation_routes_enabled_next_poll",
        "automation_routes",
        ["enabled", "next_poll_at"],
    )

    op.create_table(
        "publish_jobs",
        _uuid_column("id"),
        _uuid_column("destination_id"),
        _uuid_column("platform_variant_revision_id"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"]),
        sa.ForeignKeyConstraint(["platform_variant_revision_id"], ["platform_variant_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_publish_jobs_idempotency_key"),
    )
    op.create_index(
        "ix_publish_jobs_status_scheduled",
        "publish_jobs",
        ["status", "scheduled_for"],
    )

    op.create_table(
        "publish_attempts",
        _uuid_column("id"),
        _uuid_column("publish_job_id"),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        _json_object_column("sanitized_payload"),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        _json_object_column("remote_response"),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["publish_job_id"], ["publish_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publish_job_id", "attempt_number", name="uq_publish_attempt_number"),
    )

    op.create_table(
        "publications",
        _uuid_column("id"),
        _uuid_column("publish_job_id"),
        _uuid_column("destination_id"),
        _uuid_column("platform_variant_revision_id"),
        _json_array_column("remote_message_ids"),
        sa.Column("permalink", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reconciliation_status", sa.Text(), server_default="confirmed", nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"]),
        sa.ForeignKeyConstraint(["platform_variant_revision_id"], ["platform_variant_revisions.id"]),
        sa.ForeignKeyConstraint(["publish_job_id"], ["publish_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "destination_id",
            "platform_variant_revision_id",
            name="uq_publication_destination_variant_revision",
        ),
        sa.UniqueConstraint("publish_job_id", name="uq_publications_publish_job_id"),
    )
    op.create_index("ix_publications_published_at", "publications", [sa.text("published_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_publications_published_at", table_name="publications")
    op.drop_index("ix_publish_jobs_status_scheduled", table_name="publish_jobs")
    op.drop_index("ix_automation_routes_enabled_next_poll", table_name="automation_routes")
    op.drop_index("ix_generation_runs_status_created", table_name="generation_runs")
    op.drop_index("ix_story_revisions_story_created", table_name="story_revisions")
    op.drop_index("ix_stories_active_updated", table_name="stories")

    op.drop_table("publications")
    op.drop_table("publish_attempts")
    op.drop_table("publish_jobs")
    op.drop_table("automation_routes")
    op.drop_table("destinations")
    op.drop_table("platform_variant_revisions")
    op.drop_table("platform_variants")
    op.drop_table("content_packs")
    op.drop_table("generation_attempts")
    op.drop_table("generation_runs")
    op.drop_table("research_sources")
    op.drop_table("research_attempts")
    op.drop_table("research_runs")
    op.drop_table("ai_provider_profiles")
    op.drop_table("prompt_template_versions")
    op.drop_table("prompt_templates")
    op.drop_table("brand_profiles")
    op.drop_table("story_evidence_links")
    op.drop_table("story_revisions")
    op.drop_table("story_evidence_snapshots")
    op.drop_table("stories")
