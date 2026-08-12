"""add safe Feed clear visibility state

Revision ID: 0035_feed_clear
Revises: 0034_source_icon_discovery
"""

import sqlalchemy as sa

from alembic import op

revision = "0035_feed_clear"
down_revision = "0034_source_icon_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_items", sa.Column("feed_cleared_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        CREATE INDEX ix_content_items_feed_active_display_at
        ON content_items (COALESCE(published_at, sort_at) DESC, id DESC)
        WHERE feed_cleared_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_content_items_feed_active_score_display_at
        ON content_items (score DESC, COALESCE(published_at, sort_at) DESC, id DESC)
        WHERE feed_cleared_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_feed_active_score_display_at", table_name="content_items")
    op.drop_index("ix_content_items_feed_active_display_at", table_name="content_items")
    op.drop_column("content_items", "feed_cleared_at")
