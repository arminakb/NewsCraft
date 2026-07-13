"""add durable manual publication plans

Revision ID: 0008_manual_publication_plans
Revises: 0007_dispatch_creation_sequence
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_manual_publication_plans"
down_revision: str | None = "0007_dispatch_creation_sequence"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# These contracts are intentionally frozen in the revision instead of imported
# from application code. Alembic revisions must remain runnable after models
# evolve in later releases.
CHECKLIST_SHAPE_CONSTRAINT = (
    "CASE platform "
    "WHEN 'instagram' THEN ("
    "checklist_state ? 'copy_reviewed' AND "
    "checklist_state ? 'citations_verified' AND "
    "checklist_state ? 'media_and_alt_text_ready' AND "
    "checklist_state ? 'platform_requirements_rechecked') AND "
    "checklist_state - ARRAY['copy_reviewed', 'citations_verified', "
    "'media_and_alt_text_ready', 'platform_requirements_rechecked']::text[] = '{}'::jsonb AND ("
    "jsonb_typeof(checklist_state -> 'copy_reviewed') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'citations_verified') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'media_and_alt_text_ready') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'platform_requirements_rechecked') = 'boolean') "
    "WHEN 'x' THEN ("
    "checklist_state ? 'thread_order_reviewed' AND "
    "checklist_state ? 'citations_and_links_verified' AND "
    "checklist_state ? 'media_and_alt_text_ready' AND "
    "checklist_state ? 'platform_requirements_rechecked') AND "
    "checklist_state - ARRAY['thread_order_reviewed', 'citations_and_links_verified', "
    "'media_and_alt_text_ready', 'platform_requirements_rechecked']::text[] = '{}'::jsonb AND ("
    "jsonb_typeof(checklist_state -> 'thread_order_reviewed') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'citations_and_links_verified') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'media_and_alt_text_ready') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'platform_requirements_rechecked') = 'boolean') "
    "WHEN 'blog' THEN ("
    "checklist_state ? 'article_reviewed' AND "
    "checklist_state ? 'citations_and_links_verified' AND "
    "checklist_state ? 'seo_fields_reviewed' AND "
    "checklist_state ? 'media_and_alt_text_ready') AND "
    "checklist_state - ARRAY['article_reviewed', 'citations_and_links_verified', "
    "'seo_fields_reviewed', 'media_and_alt_text_ready']::text[] = '{}'::jsonb AND ("
    "jsonb_typeof(checklist_state -> 'article_reviewed') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'citations_and_links_verified') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'seo_fields_reviewed') = 'boolean' AND "
    "jsonb_typeof(checklist_state -> 'media_and_alt_text_ready') = 'boolean') "
    "ELSE false END"
)

READY_CHECKLIST_CONSTRAINT = (
    "status = 'cancelled' OR ((status IN ('ready', 'manual_published')) = (CASE platform "
    "WHEN 'instagram' THEN ("
    "checklist_state -> 'copy_reviewed' = 'true'::jsonb AND "
    "checklist_state -> 'citations_verified' = 'true'::jsonb AND "
    "checklist_state -> 'media_and_alt_text_ready' = 'true'::jsonb AND "
    "checklist_state -> 'platform_requirements_rechecked' = 'true'::jsonb) "
    "WHEN 'x' THEN ("
    "checklist_state -> 'thread_order_reviewed' = 'true'::jsonb AND "
    "checklist_state -> 'citations_and_links_verified' = 'true'::jsonb AND "
    "checklist_state -> 'media_and_alt_text_ready' = 'true'::jsonb AND "
    "checklist_state -> 'platform_requirements_rechecked' = 'true'::jsonb) "
    "WHEN 'blog' THEN ("
    "checklist_state -> 'article_reviewed' = 'true'::jsonb AND "
    "checklist_state -> 'citations_and_links_verified' = 'true'::jsonb AND "
    "checklist_state -> 'seo_fields_reviewed' = 'true'::jsonb AND "
    "checklist_state -> 'media_and_alt_text_ready' = 'true'::jsonb) "
    "ELSE false END))"
)


def upgrade() -> None:
    op.create_table(
        "manual_publication_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "platform_variant_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_variant_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "display_timezone",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Asia/Tehran'"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column(
            "checklist_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("operator_note", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "platform IN ('instagram', 'x', 'blog')",
            name="ck_manual_publication_platform",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'ready', 'manual_published', 'cancelled')",
            name="ck_manual_publication_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(checklist_state) = 'object'",
            name="ck_manual_publication_checklist_object",
        ),
        sa.CheckConstraint(
            CHECKLIST_SHAPE_CONSTRAINT,
            name="ck_manual_publication_checklist_shape",
        ),
        sa.CheckConstraint(
            READY_CHECKLIST_CONSTRAINT,
            name="ck_manual_publication_ready_checklist",
        ),
        sa.CheckConstraint(
            "(status = 'manual_published' AND completed_at IS NOT NULL "
            "AND external_url IS NOT NULL) OR "
            "(status <> 'manual_published' AND completed_at IS NULL "
            "AND external_url IS NULL AND operator_note IS NULL)",
            name="ck_manual_publication_completion",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_manual_publication_active_revision",
        "manual_publication_plans",
        ["platform_variant_revision_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('planned', 'ready')"),
    )
    op.create_index(
        "ix_manual_publication_schedule",
        "manual_publication_plans",
        ["scheduled_for", "id"],
        unique=False,
    )
    op.create_index(
        "ix_manual_publication_history",
        "manual_publication_plans",
        [sa.text("completed_at DESC"), sa.text("id DESC")],
        unique=False,
        postgresql_where=sa.text("status = 'manual_published'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_manual_publication_history",
        table_name="manual_publication_plans",
    )
    op.drop_index(
        "ix_manual_publication_schedule",
        table_name="manual_publication_plans",
    )
    op.drop_index(
        "uq_manual_publication_active_revision",
        table_name="manual_publication_plans",
    )
    op.drop_table("manual_publication_plans")
