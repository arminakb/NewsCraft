"""add content draft workflow

Revision ID: 0002_content_workflow
Revises: 0001_initial_ingestion_schema
Create Date: 2026-07-04
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_content_workflow"
down_revision = "0001_initial_ingestion_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_items.id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("human_notes", sa.Text(), nullable=True),
        sa.Column(
            "draft_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_content_drafts_content_item", "content_drafts", ["content_item_id"])


def downgrade() -> None:
    op.drop_index("ix_content_drafts_content_item", table_name="content_drafts")
    op.drop_table("content_drafts")
