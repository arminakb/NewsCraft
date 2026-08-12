"""add durable continuous Source Collection ingestion subscriptions

Revision ID: 0033_continuous_source_collection_ingestion
Revises: 0032_source_collections
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0033_continuous_source_collection_ingestion"
down_revision = "0032_source_collections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_collection_ingestion_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_collection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_collection_name_at_start", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), server_default="continuous", nullable=False),
        sa.Column("status", sa.Text(), server_default="starting", nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_cycle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_cycle_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cycle_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", sa.Text(), server_default="operator", nullable=False),
        sa.Column("last_cycle_status", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("current_cycle_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("current_cycle_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("mode = 'continuous'", name="ck_source_collection_ingestion_subscription_mode"),
        sa.CheckConstraint(
            "status IN ('starting', 'running', 'stopping', 'stopped', 'error')",
            name="ck_source_collection_ingestion_subscription_status",
        ),
        sa.CheckConstraint("interval_minutes BETWEEN 1 AND 1440", name="ck_source_collection_ingestion_interval"),
        sa.CheckConstraint("cycle_count >= 0", name="ck_source_collection_ingestion_cycle_count"),
        sa.ForeignKeyConstraint(
            ["source_collection_id"],
            ["source_collections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_cycle_job_id"],
            ["workflow_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_cycle_run_id"],
            ["ingest_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_source_collection_ingestion_subscriptions_idempotency",
        ),
    )
    op.create_index(
        "uq_source_collection_ingestion_subscription_active",
        "source_collection_ingestion_subscriptions",
        ["source_collection_id"],
        unique=True,
        postgresql_where=sa.text(
            "source_collection_id IS NOT NULL AND status IN ('starting', 'running', 'stopping')"
        ),
    )
    op.create_index(
        "ix_source_collection_ingestion_subscription_due",
        "source_collection_ingestion_subscriptions",
        ["status", "next_cycle_at"],
    )
    op.create_index(
        "ix_source_collection_ingestion_subscription_collection",
        "source_collection_ingestion_subscriptions",
        ["source_collection_id", "created_at"],
    )

    op.add_column(
        "ingest_runs",
        sa.Column("continuous_subscription_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("ingest_runs", sa.Column("continuous_cycle_number", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_ingest_runs_continuous_subscription",
        "ingest_runs",
        "source_collection_ingestion_subscriptions",
        ["continuous_subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ingest_runs_continuous_subscription_cycle",
        "ingest_runs",
        ["continuous_subscription_id", "continuous_cycle_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_runs_continuous_subscription_cycle", table_name="ingest_runs")
    op.drop_constraint("fk_ingest_runs_continuous_subscription", "ingest_runs", type_="foreignkey")
    op.drop_column("ingest_runs", "continuous_cycle_number")
    op.drop_column("ingest_runs", "continuous_subscription_id")
    op.drop_index(
        "ix_source_collection_ingestion_subscription_collection",
        table_name="source_collection_ingestion_subscriptions",
    )
    op.drop_index(
        "ix_source_collection_ingestion_subscription_due",
        table_name="source_collection_ingestion_subscriptions",
    )
    op.drop_index(
        "uq_source_collection_ingestion_subscription_active",
        table_name="source_collection_ingestion_subscriptions",
    )
    op.drop_table("source_collection_ingestion_subscriptions")
