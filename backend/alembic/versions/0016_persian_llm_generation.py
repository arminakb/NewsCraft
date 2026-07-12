"""add one-pass Persian LLM generation metadata

Revision ID: 0016_persian_llm_generation
Revises: 0015_shortlist_selection_execution
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016_persian_llm_generation"
down_revision = "0015_shortlist_selection_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "editorial_briefs",
        sa.Column(
            "evidence_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "editorial_briefs",
        sa.Column(
            "generation_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "telegram_drafts",
        sa.Column(
            "evidence_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "telegram_drafts",
        sa.Column(
            "generation_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "draft_quality_reports",
        sa.Column(
            "rubric_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "draft_quality_reports",
        sa.Column(
            "evaluation_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("draft_quality_reports", "evaluation_metadata_json")
    op.drop_column("draft_quality_reports", "rubric_json")
    op.drop_column("telegram_drafts", "generation_metadata_json")
    op.drop_column("telegram_drafts", "evidence_ids_json")
    op.drop_column("editorial_briefs", "generation_metadata_json")
    op.drop_column("editorial_briefs", "evidence_ids_json")
