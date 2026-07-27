"""persist operator source deletion

Revision ID: 0023_source_soft_deletion
Revises: 0022_article_canonical_classification
"""

import sqlalchemy as sa

from alembic import op

revision = "0023_source_soft_deletion"
down_revision = "0022_article_canonical_classification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_sources_deleted_at",
        "sources",
        ["deleted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sources_deleted_at", table_name="sources")
    op.drop_column("sources", "deleted_at")
