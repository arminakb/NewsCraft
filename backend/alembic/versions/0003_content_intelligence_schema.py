"""add content intelligence schema

Revision ID: 0003_content_intelligence_schema
Revises: 0002_content_workflow
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003_content_intelligence_schema"
down_revision = "0002_content_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sources", sa.Column("last_http_status", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("last_error_type", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("last_error_message", sa.Text(), nullable=True))
    op.add_column("sources", sa.Column("last_parse_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sources", sa.Column("last_suitable_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sources", sa.Column("last_media_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sources", sa.Column("health_status", sa.Text(), server_default="unknown", nullable=False))
    op.add_column("sources", sa.Column("disabled_reason", sa.Text(), nullable=True))

    op.add_column("content_items", sa.Column("content_type", sa.Text(), server_default="article", nullable=False))
    op.add_column(
        "content_items",
        sa.Column("content_type_confidence", sa.Numeric(), server_default="0", nullable=False),
    )
    op.add_column(
        "content_items",
        sa.Column(
            "classification_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "content_items",
        sa.Column(
            "classification_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("content_items", sa.Column("rewrite_bucket", sa.Text(), nullable=True))
    op.add_column("content_items", sa.Column("freshness_bucket", sa.Text(), server_default="unknown", nullable=False))
    op.add_column("content_items", sa.Column("source_tier", sa.Text(), server_default="unknown", nullable=False))
    op.add_column(
        "content_items",
        sa.Column("quality_status", sa.Text(), server_default="needs_review", nullable=False),
    )
    op.add_column(
        "content_items",
        sa.Column("is_rewrite_ready", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("content_items", sa.Column("rewrite_ready_reason", sa.Text(), nullable=True))
    op.add_column(
        "content_items",
        sa.Column(
            "rewrite_blockers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "content_items",
        sa.Column(
            "score_breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "content_items",
        sa.Column(
            "ranking_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("content_items", sa.Column("title_quality", sa.Text(), server_default="unknown", nullable=False))
    op.add_column(
        "content_items",
        sa.Column("title_was_generated", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("content_items", sa.Column("content_intent", sa.Text(), nullable=True))

    op.add_column("media_assets", sa.Column("media_quality", sa.Text(), server_default="unknown", nullable=False))
    op.add_column("media_assets", sa.Column("media_confidence", sa.Numeric(), server_default="0", nullable=False))
    op.add_column(
        "media_assets",
        sa.Column("is_primary_candidate", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("media_assets", sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("media_assets", sa.Column("media_source_type", sa.Text(), server_default="external", nullable=False))
    op.add_column("media_assets", sa.Column("asset_role", sa.Text(), server_default="unknown", nullable=False))

    op.create_table(
        "rewrite_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bucket_type", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_item_id", "bucket_type", name="uq_rewrite_candidates_content_bucket"),
    )
    op.create_index(
        "ix_rewrite_candidates_bucket_status",
        "rewrite_candidates",
        ["bucket_type", "status", sa.text("priority_score DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_rewrite_candidates_bucket_status", table_name="rewrite_candidates")
    op.drop_table("rewrite_candidates")

    for column in (
        "asset_role",
        "media_source_type",
        "is_primary",
        "is_primary_candidate",
        "media_confidence",
        "media_quality",
    ):
        op.drop_column("media_assets", column)

    for column in (
        "content_intent",
        "title_was_generated",
        "title_quality",
        "ranking_metadata",
        "score_breakdown",
        "rewrite_blockers",
        "rewrite_ready_reason",
        "is_rewrite_ready",
        "quality_status",
        "source_tier",
        "freshness_bucket",
        "rewrite_bucket",
        "classification_metadata",
        "classification_reasons",
        "content_type_confidence",
        "content_type",
    ):
        op.drop_column("content_items", column)

    for column in (
        "disabled_reason",
        "health_status",
        "last_media_count",
        "last_suitable_count",
        "last_parse_count",
        "last_error_message",
        "last_error_type",
        "last_http_status",
        "failure_count",
        "last_failure_at",
        "last_success_at",
    ):
        op.drop_column("sources", column)
