"""add telegram drafts

Revision ID: 0008_telegram_drafts
Revises: 0007_editorial_briefs
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008_telegram_drafts"
down_revision = "0007_editorial_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brief_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "hashtags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_links_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "warnings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["brief_id"], ["editorial_briefs.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_drafts_production_run_created",
        "telegram_drafts",
        ["production_run_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_telegram_drafts_status", "telegram_drafts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_telegram_drafts_status", table_name="telegram_drafts")
    op.drop_index("ix_telegram_drafts_production_run_created", table_name="telegram_drafts")
    op.drop_table("telegram_drafts")
