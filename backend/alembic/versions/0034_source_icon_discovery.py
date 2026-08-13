"""add durable source icon discovery metadata

Revision ID: 0034_source_icon_discovery
Revises: 0033_continuous_source_collection_ingestion
"""

import sqlalchemy as sa

from alembic import op

revision = "0034_source_icon_discovery"
down_revision = "0033_continuous_source_collection_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("icon_url", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("icon_source", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("icon_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("icon_status", sa.Text(), server_default="pending", nullable=False))
    op.add_column("sources", sa.Column("icon_storage_path", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("icon_original_url", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("icon_mime_type", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("icon_width", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("icon_height", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("icon_failure_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sources", sa.Column("icon_next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("icon_last_error", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("icon_enqueued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("icon_attempt", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint(
        "ck_sources_icon_status",
        "sources",
        "icon_status IN ('pending', 'queued', 'resolved', 'retryable', 'unavailable')",
    )
    op.create_index(
        "ix_sources_icon_discovery",
        "sources",
        ["active", "platform", "icon_status", "icon_next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sources_icon_discovery", table_name="sources")
    op.drop_constraint("ck_sources_icon_status", "sources", type_="check")
    for name in (
        "icon_attempt",
        "icon_enqueued_at",
        "icon_last_error",
        "icon_next_retry_at",
        "icon_failure_count",
        "icon_height",
        "icon_width",
        "icon_mime_type",
        "icon_original_url",
        "icon_storage_path",
        "icon_status",
        "icon_updated_at",
        "icon_source",
        "icon_url",
    ):
        op.drop_column("sources", name)
