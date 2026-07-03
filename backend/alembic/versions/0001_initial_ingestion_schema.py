"""initial ingestion schema

Revision ID: 0001_initial_ingestion_schema
Revises:
Create Date: 2026-07-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_ingestion_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("homepage_url", sa.Text(), nullable=True),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("source_group", sa.Text(), nullable=False),
        sa.Column("language_hint", sa.Text(), nullable=True),
        sa.Column("default_timezone", sa.Text(), server_default="UTC", nullable=False),
        sa.Column(
            "normalization_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("fetch_interval_minutes", sa.Integer(), server_default="1440", nullable=False),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "feed_url", name="uq_sources_platform_feed_url"),
        sa.UniqueConstraint("platform", "telegram_username", name="uq_sources_platform_telegram_username"),
    )
    op.create_table(
        "ingest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "stats", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "raw_payloads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload_kind", sa.Text(), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "headers", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("body_sha256", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column(
            "parser_warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["ingest_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "content_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("canonical_url_hash", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("title_fingerprint", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_html_sanitized", sa.Text(), nullable=True),
        sa.Column("language_code", sa.Text(), nullable=True),
        sa.Column("script_code", sa.Text(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column(
            "authors", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_raw", sa.Text(), nullable=True),
        sa.Column("date_source", sa.Text(), nullable=True),
        sa.Column("date_parse_status", sa.Text(), nullable=False),
        sa.Column("primary_source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("primary_image_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), server_default="new", nullable=False),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("duplicate_of_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["primary_source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_payload_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_id_raw", sa.Text(), nullable=True),
        sa.Column("external_id_norm", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_url_norm", sa.Text(), nullable=True),
        sa.Column("canonical_url_candidate", sa.Text(), nullable=True),
        sa.Column("title_raw", sa.Text(), nullable=True),
        sa.Column("summary_raw", sa.Text(), nullable=True),
        sa.Column("content_html_raw", sa.Text(), nullable=True),
        sa.Column("content_text_raw", sa.Text(), nullable=True),
        sa.Column("author_raw", sa.Text(), nullable=True),
        sa.Column("categories", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("published_raw", sa.Text(), nullable=True),
        sa.Column(
            "parser_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["raw_payload_id"], ["raw_payloads.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["ingest_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_source_item_external",
        "source_items",
        ["source_id", "external_id_norm"],
        unique=True,
        postgresql_where=sa.text("external_id_norm IS NOT NULL"),
    )
    op.create_index("ix_source_items_seen", "source_items", ["source_id", "last_seen_at"], unique=False)
    op.create_table(
        "item_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("identity_type", sa.Text(), nullable=False),
        sa.Column("identity_value", sa.Text(), nullable=False),
        sa.Column("identity_hash", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=False),
        sa.Column("is_strong", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_identity_global_strong",
        "item_identities",
        ["identity_type", "identity_hash"],
        unique=True,
        postgresql_where=sa.text("scope = 'global' AND is_strong"),
    )
    op.create_index(
        "uq_identity_source_strong",
        "item_identities",
        ["source_id", "identity_type", "identity_hash"],
        unique=True,
        postgresql_where=sa.text("scope = 'source' AND is_strong"),
    )
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(), nullable=True),
        sa.Column("byte_length", sa.BigInteger(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("source_field", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("fetch_status", sa.Text(), nullable=False),
        sa.Column(
            "raw_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "item_media",
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confidence", sa.Numeric(), server_default="1.0", nullable=False),
        sa.Column("extracted_from", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"]),
        sa.PrimaryKeyConstraint("content_item_id", "media_asset_id", "role"),
    )


def downgrade() -> None:
    op.drop_table("item_media")
    op.drop_table("media_assets")
    op.drop_index(
        "uq_identity_source_strong",
        table_name="item_identities",
        postgresql_where=sa.text("scope = 'source' AND is_strong"),
    )
    op.drop_index(
        "uq_identity_global_strong",
        table_name="item_identities",
        postgresql_where=sa.text("scope = 'global' AND is_strong"),
    )
    op.drop_table("item_identities")
    op.drop_index("ix_source_items_seen", table_name="source_items")
    op.drop_index(
        "uq_source_item_external", table_name="source_items", postgresql_where=sa.text("external_id_norm IS NOT NULL")
    )
    op.drop_table("source_items")
    op.drop_table("content_items")
    op.drop_table("raw_payloads")
    op.drop_table("ingest_runs")
    op.drop_table("sources")
