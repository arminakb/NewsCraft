"""add visual briefs

Revision ID: 0010_visual_briefs
Revises: 0009_draft_quality_reports
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_visual_briefs"
down_revision = "0009_draft_quality_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("selected_media_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("needs_generation", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("visual_prompt", sa.Text(), nullable=True),
        sa.Column("visual_style", sa.Text(), nullable=True),
        sa.Column("provider_name", sa.Text(), nullable=True),
        sa.Column(
            "provider_request_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "provider_result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.ForeignKeyConstraint(["selected_media_asset_id"], ["media_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_visual_briefs_production_run_created",
        "visual_briefs",
        ["production_run_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_visual_briefs_status", "visual_briefs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_visual_briefs_status", table_name="visual_briefs")
    op.drop_index("ix_visual_briefs_production_run_created", table_name="visual_briefs")
    op.drop_table("visual_briefs")
