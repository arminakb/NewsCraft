"""add telegram post packages

Revision ID: 0011_telegram_post_packages
Revises: 0010_visual_briefs
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_telegram_post_packages"
down_revision = "0010_visual_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_post_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("image_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "package_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("approval_status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["telegram_drafts.id"]),
        sa.ForeignKeyConstraint(["image_request_id"], ["visual_briefs.id"]),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_post_packages_run_created",
        "telegram_post_packages",
        ["production_run_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_telegram_post_packages_approval_status",
        "telegram_post_packages",
        ["approval_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_post_packages_approval_status", table_name="telegram_post_packages")
    op.drop_index("ix_telegram_post_packages_run_created", table_name="telegram_post_packages")
    op.drop_table("telegram_post_packages")
