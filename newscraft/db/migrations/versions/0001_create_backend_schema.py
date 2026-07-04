"""create backend postgres schema

Revision ID: 0001_create_backend_schema
Revises:
Create Date: 2026-07-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_create_backend_schema"
down_revision = None
branch_labels = None
depends_on = None


jsonb = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000)),
        sa.Column("external_id", sa.String(length=255)),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=80)),
        sa.Column("connector", sa.String(length=80)),
        sa.Column("source_group", sa.String(length=120)),
        sa.Column("author", sa.String(length=255)),
        sa.Column("summary", sa.Text()),
        sa.Column("content", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("category", sa.String(length=120)),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="new"),
        sa.Column("language", sa.String(length=20)),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("raw_data", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("url", name="uq_articles_url"),
        sa.UniqueConstraint("source", "external_id", name="uq_articles_source_external_id"),
    )
    op.create_index("ix_articles_status", "articles", ["status"])

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("connector", sa.String(length=80), nullable=False),
        sa.Column("url", sa.String(length=1000)),
        sa.Column("language", sa.String(length=20)),
        sa.Column("category", sa.String(length=120)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("config", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="running"),
        sa.Column("selected_sources", jsonb, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("total_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_saved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "source_run_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ingestion_run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id")),
        sa.Column("source_name", sa.String(length=255)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="running"),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "approved_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id")),
        sa.Column("source", sa.String(length=255)),
        sa.Column("source_type", sa.String(length=80)),
        sa.Column("connector", sa.String(length=80)),
        sa.Column("source_group", sa.String(length=120)),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("summary", sa.Text()),
        sa.Column("category", sa.String(length=120)),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text()),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="approved"),
        sa.UniqueConstraint("url", name="uq_approved_articles_url"),
    )

    op.create_table(
        "paper_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id")),
        sa.Column("pdf_path", sa.String(length=1000)),
        sa.Column("text_path", sa.String(length=1000)),
        sa.Column("notebooklm_brief_path", sa.String(length=1000)),
        sa.Column("instagram_brief_path", sa.String(length=1000)),
        sa.Column("podcast_brief_path", sa.String(length=1000)),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("article_id", name="uq_paper_assets_article_id"),
    )

    op.create_table(
        "content_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("human_notes", sa.Text()),
        sa.Column("metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("content_drafts")
    op.drop_table("paper_assets")
    op.drop_table("approved_articles")
    op.drop_table("source_run_logs")
    op.drop_table("ingestion_runs")
    op.drop_table("sources")
    op.drop_index("ix_articles_status", table_name="articles")
    op.drop_table("articles")
