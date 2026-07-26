"""enforce research and generation state contracts

Revision ID: 0021_editorial_state_contracts
Revises: 0020_article_query_indexes
"""

from alembic import op

revision = "0021_editorial_state_contracts"
down_revision = "0020_article_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_research_runs_status",
        "research_runs",
        "status IN ('queued', 'running', 'succeeded', 'needs_review', 'failed')",
    )
    op.create_check_constraint(
        "ck_generation_runs_status",
        "generation_runs",
        "status IN ('running', 'succeeded', 'completed', 'failed')",
    )
    op.create_check_constraint(
        "ck_content_packs_status",
        "content_packs",
        "status IN ('draft', 'ready')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_content_packs_status", "content_packs", type_="check")
    op.drop_constraint("ck_generation_runs_status", "generation_runs", type_="check")
    op.drop_constraint("ck_research_runs_status", "research_runs", type_="check")
