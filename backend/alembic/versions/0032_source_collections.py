"""add Source Collection membership and ingest snapshots

Revision ID: 0032_source_collections
Revises: 0031_retire_obsolete_workflow_nodes
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0032_source_collections"
down_revision = "0031_retire_obsolete_workflow_nodes"
branch_labels = None
depends_on = None


def _uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _created_at_column(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_index(
        "ix_sources_collection_search_order",
        "sources",
        ["source_group", "name", "id"],
    )
    op.create_table(
        "source_collections",
        _uuid_column("id"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 60",
            name="ck_source_collections_name",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_source_collections_normalized_name"),
    )
    op.create_index(
        "ix_source_collections_name_lookup",
        "source_collections",
        ["normalized_name", "id"],
    )

    op.create_table(
        "source_collection_memberships",
        _uuid_column("collection_id"),
        _uuid_column("source_id"),
        _created_at_column(),
        sa.ForeignKeyConstraint(["collection_id"], ["source_collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("collection_id", "source_id"),
    )
    op.create_index(
        "ix_source_collection_memberships_collection_source",
        "source_collection_memberships",
        ["collection_id", "source_id"],
    )
    op.create_index(
        "ix_source_collection_memberships_source_collection",
        "source_collection_memberships",
        ["source_id", "collection_id"],
    )

    op.add_column(
        "ingest_runs",
        sa.Column("source_collection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("ingest_runs", sa.Column("source_collection_name_at_start", sa.Text(), nullable=True))
    op.add_column("ingest_runs", sa.Column("source_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("ingest_runs", sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("ingest_runs", sa.Column("success_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("ingest_runs", sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False))
    op.create_foreign_key(
        "fk_ingest_runs_source_collection",
        "ingest_runs",
        "source_collections",
        ["source_collection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_ingest_runs_active_source_collection",
        "ingest_runs",
        ["source_collection_id"],
        unique=True,
        postgresql_where=sa.text(
            "source_collection_id IS NOT NULL AND status IN ('queued', 'running')"
        ),
    )
    op.create_index(
        "ix_ingest_runs_source_collection_started",
        "ingest_runs",
        ["source_collection_id", "started_at"],
    )

    op.create_table(
        "ingest_run_source_snapshots",
        _uuid_column("id"),
        _uuid_column("ingest_run_id"),
        _uuid_column("source_id", nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("telegram_username", sa.Text(), nullable=True),
        sa.Column("default_timezone", sa.Text(), server_default="UTC", nullable=False),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        _created_at_column(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'skipped')",
            name="ck_ingest_run_source_snapshot_status",
        ),
        sa.ForeignKeyConstraint(["ingest_run_id"], ["ingest_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingest_run_id", "source_id", name="uq_ingest_run_source_snapshot_source"),
    )
    op.create_index(
        "ix_ingest_run_source_snapshots_run_status",
        "ingest_run_source_snapshots",
        ["ingest_run_id", "status"],
    )
    op.create_index(
        "ix_ingest_run_source_snapshots_source",
        "ingest_run_source_snapshots",
        ["source_id", "ingest_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_run_source_snapshots_source", table_name="ingest_run_source_snapshots")
    op.drop_index("ix_ingest_run_source_snapshots_run_status", table_name="ingest_run_source_snapshots")
    op.drop_table("ingest_run_source_snapshots")
    op.drop_index("ix_ingest_runs_source_collection_started", table_name="ingest_runs")
    op.drop_index("uq_ingest_runs_active_source_collection", table_name="ingest_runs")
    op.drop_constraint("fk_ingest_runs_source_collection", "ingest_runs", type_="foreignkey")
    op.drop_column("ingest_runs", "failure_count")
    op.drop_column("ingest_runs", "success_count")
    op.drop_column("ingest_runs", "processed_count")
    op.drop_column("ingest_runs", "source_count")
    op.drop_column("ingest_runs", "source_collection_name_at_start")
    op.drop_column("ingest_runs", "source_collection_id")
    op.drop_index("ix_source_collection_memberships_source_collection", table_name="source_collection_memberships")
    op.drop_index("ix_source_collection_memberships_collection_source", table_name="source_collection_memberships")
    op.drop_table("source_collection_memberships")
    op.drop_index("ix_source_collections_name_lookup", table_name="source_collections")
    op.drop_table("source_collections")
    op.drop_index("ix_sources_collection_search_order", table_name="sources")
