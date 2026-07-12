"""add Telegram automation vertical persistence

Revision ID: 0006_telegram_automation_vertical
Revises: 0005_job_engine_and_scheduling
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_telegram_automation_vertical"
down_revision: str | None = "0005_job_engine_and_scheduling"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _created_at_column(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.alter_column("alembic_version", "version_num", type_=sa.String(length=64))

    op.create_table(
        "telegram_source_configs",
        _uuid_column("source_id"),
        sa.Column("access_mode", sa.Text(), nullable=False),
        sa.Column("channel_ref", sa.Text(), nullable=False),
        sa.Column("peer_id", sa.Text(), nullable=True),
        sa.Column("api_id_secret_ref", sa.Text(), nullable=True),
        sa.Column("api_hash_secret_ref", sa.Text(), nullable=True),
        sa.Column("session_secret_ref", sa.Text(), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.CheckConstraint(
            "access_mode IN ('public_html', 'mtproto_user')",
            name="ck_telegram_source_access_mode",
        ),
        sa.CheckConstraint(
            "(access_mode = 'public_html' AND api_id_secret_ref IS NULL AND api_hash_secret_ref IS NULL "
            "AND session_secret_ref IS NULL) OR "
            "(access_mode = 'mtproto_user' AND api_id_secret_ref IS NOT NULL AND api_hash_secret_ref IS NOT NULL "
            "AND session_secret_ref IS NOT NULL)",
            name="ck_telegram_source_secret_mode",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id"),
        sa.UniqueConstraint("access_mode", "channel_ref", name="uq_telegram_source_mode_channel"),
    )

    op.create_table(
        "automation_dispatches",
        _uuid_column("id"),
        _uuid_column("route_id"),
        _uuid_column("source_item_id"),
        _uuid_column("story_revision_id"),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("source_fingerprint", sa.Text(), nullable=False),
        sa.Column("source_message_ids", postgresql.ARRAY(sa.BigInteger()), nullable=False),
        sa.Column("dispatch_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="captured", nullable=False),
        _uuid_column("generation_run_id", nullable=True),
        _uuid_column("variant_revision_id", nullable=True),
        _uuid_column("publish_job_id", nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.CheckConstraint(
            "dispatch_kind IN ('live', 'backfill', 'dry_run', 'source_edit')",
            name="ck_automation_dispatch_kind",
        ),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"]),
        sa.ForeignKeyConstraint(["publish_job_id"], ["publish_jobs.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["automation_routes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_item_id"], ["source_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["story_revision_id"], ["story_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["variant_revision_id"], ["platform_variant_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_id", "source_key", name="uq_automation_dispatch_route_source"),
    )
    op.create_index(
        "ix_automation_dispatch_route_created",
        "automation_dispatches",
        ["route_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "publish_operation_receipts",
        _uuid_column("id"),
        _uuid_column("publish_job_id"),
        sa.Column("operation_index", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "remote_message_ids",
            postgresql.ARRAY(sa.BigInteger()),
            server_default=sa.text("'{}'::bigint[]"),
            nullable=False,
        ),
        sa.Column(
            "response_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ambiguous_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.ForeignKeyConstraint(["publish_job_id"], ["publish_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publish_job_id", "operation_key", name="uq_publish_operation_job_key"),
        sa.UniqueConstraint("publish_job_id", "operation_index", name="uq_publish_operation_job_index"),
    )
    op.create_index(
        "ix_publish_operation_retry",
        "publish_operation_receipts",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("publish_operation_receipts")
    op.drop_table("automation_dispatches")
    op.drop_table("telegram_source_configs")
