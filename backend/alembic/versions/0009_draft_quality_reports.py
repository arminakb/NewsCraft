"""add draft quality reports

Revision ID: 0009_draft_quality_reports
Revises: 0008_telegram_drafts
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0009_draft_quality_reports"
down_revision = "0008_telegram_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "draft_quality_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(), server_default="0", nullable=False),
        sa.Column(
            "factuality_warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "unsupported_claims_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "style_warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "required_revisions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["telegram_drafts.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_draft_quality_reports_run_created",
        "draft_quality_reports",
        ["production_run_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_draft_quality_reports_draft", "draft_quality_reports", ["draft_id"])
    op.create_index("ix_draft_quality_reports_status", "draft_quality_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_draft_quality_reports_status", table_name="draft_quality_reports")
    op.drop_index("ix_draft_quality_reports_draft", table_name="draft_quality_reports")
    op.drop_index("ix_draft_quality_reports_run_created", table_name="draft_quality_reports")
    op.drop_table("draft_quality_reports")
