"""add editorial briefs

Revision ID: 0007_editorial_briefs
Revises: 0006_extraction_enrichment_results
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_editorial_briefs"
down_revision = "0006_extraction_enrichment_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column(
            "key_facts_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_claims_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "unsafe_or_unverified_claims_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("tone", sa.Text(), nullable=True),
        sa.Column(
            "do_not_say_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_editorial_briefs_production_run_created",
        "editorial_briefs",
        ["production_run_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_editorial_briefs_production_run_created", table_name="editorial_briefs")
    op.drop_table("editorial_briefs")
