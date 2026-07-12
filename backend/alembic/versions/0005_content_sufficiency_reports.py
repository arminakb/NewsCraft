"""add content sufficiency reports

Revision ID: 0005_content_sufficiency_reports
Revises: 0004_content_production_foundation
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_content_sufficiency_reports"
down_revision = "0004_content_production_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_sufficiency_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score", sa.Numeric(), server_default="0", nullable=False),
        sa.Column(
            "reasons_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("allowed_next_step", sa.Text(), nullable=True),
        sa.Column(
            "blocked_steps_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "minimum_needed_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "input_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_sufficiency_reports_run_created",
        "content_sufficiency_reports",
        ["production_run_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_content_sufficiency_reports_item_created",
        "content_sufficiency_reports",
        ["content_item_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_content_sufficiency_reports_status", "content_sufficiency_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_content_sufficiency_reports_status", table_name="content_sufficiency_reports")
    op.drop_index("ix_content_sufficiency_reports_item_created", table_name="content_sufficiency_reports")
    op.drop_index("ix_content_sufficiency_reports_run_created", table_name="content_sufficiency_reports")
    op.drop_table("content_sufficiency_reports")
