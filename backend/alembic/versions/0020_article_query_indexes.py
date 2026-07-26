"""add article query indexes

Revision ID: 0020_article_query_indexes
Revises: 0019_story_state_contract
"""

from alembic import op

revision = "0020_article_query_indexes"
down_revision = "0019_story_state_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_content_items_search
        ON content_items
        USING gin (
          to_tsvector(
            'simple'::regconfig,
            COALESCE(title, '') || ' ' || COALESCE(content_text, '')
          )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_content_items_display_at
        ON content_items (COALESCE(published_at, sort_at) DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_content_items_score_display_at
        ON content_items (score DESC, COALESCE(published_at, sort_at) DESC, id DESC)
        """
    )
    op.create_index(
        "ix_story_evidence_content_item",
        "story_evidence_snapshots",
        ["content_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_story_evidence_content_item", table_name="story_evidence_snapshots")
    op.drop_index("ix_content_items_score_display_at", table_name="content_items")
    op.drop_index("ix_content_items_display_at", table_name="content_items")
    op.drop_index("ix_content_items_search", table_name="content_items")
