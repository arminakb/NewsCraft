"""add job engine and scheduling persistence

Revision ID: 0005_job_engine_and_scheduling
Revises: 0004_platform_spine
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_job_engine_and_scheduling"
down_revision = "0004_platform_spine"
branch_labels = None
depends_on = None


def _uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def _json_object_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


def _created_at_column(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "workflow_jobs",
        _uuid_column("id"),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        _json_object_column("payload"),
        _json_object_column("result"),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("pause_sensitive", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_workflow_jobs_progress"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_jobs_idempotency_key"),
    )
    op.create_index(
        "ix_workflow_jobs_claim",
        "workflow_jobs",
        ["status", "scheduled_for", sa.text("priority DESC"), "created_at"],
    )
    op.create_index(
        "ix_workflow_jobs_lease_expiry",
        "workflow_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "ix_workflow_jobs_attention",
        "workflow_jobs",
        ["status", "error_class", sa.text("updated_at DESC")],
    )

    op.create_table(
        "workflow_events",
        _uuid_column("id"),
        _uuid_column("workflow_job_id", nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        _json_object_column("event_data"),
        _created_at_column(),
        sa.ForeignKeyConstraint(["workflow_job_id"], ["workflow_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_events_job_created",
        "workflow_events",
        ["workflow_job_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_workflow_events_created",
        "workflow_events",
        [sa.text("created_at DESC")],
    )

    op.create_table(
        "workflow_schedules",
        _uuid_column("id"),
        sa.Column("schedule_key", sa.Text(), nullable=False),
        _uuid_column("source_id", nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        _json_object_column("payload"),
        sa.Column("schedule_kind", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Asia/Tehran", nullable=False),
        sa.Column("local_time", sa.Text(), nullable=True),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("pause_sensitive", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _created_at_column("updated_at"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schedule_key", name="uq_workflow_schedules_schedule_key"),
    )
    op.create_index(
        "ix_workflow_schedules_due",
        "workflow_schedules",
        ["enabled", "next_run_at"],
    )

    automation_controls = op.create_table(
        "automation_controls",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("global_pause", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        automation_controls,
        [
            {
                "id": "global",
                "global_pause": False,
                "dry_run": False,
            }
        ],
    )

    op.create_table(
        "runtime_heartbeats",
        sa.Column("component_id", sa.Text(), nullable=False),
        sa.Column("component_type", sa.Text(), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        _json_object_column("metadata"),
        sa.PrimaryKeyConstraint("component_id"),
    )
    op.create_index(
        "ix_runtime_heartbeats_type_observed",
        "runtime_heartbeats",
        ["component_type", sa.text("observed_at DESC")],
    )

    op.add_column("sources", sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_sources_next_fetch_at", "sources", ["next_fetch_at"])

    op.add_column("publish_jobs", sa.Column("workflow_job_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_publish_jobs_workflow_job_id_workflow_jobs",
        "publish_jobs",
        "workflow_jobs",
        ["workflow_job_id"],
        ["id"],
    )
    op.create_index("ix_publish_jobs_workflow_job_id", "publish_jobs", ["workflow_job_id"])


def downgrade() -> None:
    op.drop_constraint(
        "fk_publish_jobs_workflow_job_id_workflow_jobs",
        "publish_jobs",
        type_="foreignkey",
    )
    op.drop_index("ix_publish_jobs_workflow_job_id", table_name="publish_jobs")
    op.drop_column("publish_jobs", "workflow_job_id")

    op.drop_index("ix_sources_next_fetch_at", table_name="sources")
    op.drop_column("sources", "next_fetch_at")

    op.drop_index("ix_runtime_heartbeats_type_observed", table_name="runtime_heartbeats")
    op.drop_table("runtime_heartbeats")

    op.drop_index("ix_workflow_schedules_due", table_name="workflow_schedules")
    op.drop_table("workflow_schedules")

    op.drop_index("ix_workflow_events_created", table_name="workflow_events")
    op.drop_index("ix_workflow_events_job_created", table_name="workflow_events")
    op.drop_table("workflow_events")

    op.drop_table("automation_controls")

    op.drop_index("ix_workflow_jobs_attention", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_lease_expiry", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_claim", table_name="workflow_jobs")
    op.drop_table("workflow_jobs")
