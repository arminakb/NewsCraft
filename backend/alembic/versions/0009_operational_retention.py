"""add operational retention policy and durable preview runs

Revision ID: 0009_operational_retention
Revises: 0008_manual_publication_plans
Create Date: 2026-07-13
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_operational_retention"
down_revision: str | None = "0008_manual_publication_plans"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    retention_policies = op.create_table(
        "retention_policies",
        sa.Column(
            "id",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'global'"),
        ),
        sa.Column(
            "raw_payload_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "completed_job_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("90"),
        ),
        sa.Column(
            "attempt_metadata_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("90"),
        ),
        sa.Column(
            "export_artifact_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("14"),
        ),
        sa.Column(
            "unreferenced_media_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("30"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 'global'", name="ck_retention_policy_singleton"),
        sa.CheckConstraint(
            "raw_payload_days BETWEEN 7 AND 3650",
            name="ck_retention_policy_raw_payload_days",
        ),
        sa.CheckConstraint(
            "completed_job_days BETWEEN 14 AND 3650",
            name="ck_retention_policy_completed_job_days",
        ),
        sa.CheckConstraint(
            "attempt_metadata_days BETWEEN 14 AND 3650",
            name="ck_retention_policy_attempt_metadata_days",
        ),
        sa.CheckConstraint(
            "export_artifact_days BETWEEN 1 AND 3650",
            name="ck_retention_policy_export_artifact_days",
        ),
        sa.CheckConstraint(
            "unreferenced_media_days BETWEEN 7 AND 3650",
            name="ck_retention_policy_unreferenced_media_days",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        retention_policies,
        [
            {
                "id": "global",
                "raw_payload_days": 30,
                "completed_job_days": 90,
                "attempt_metadata_days": 90,
                "export_artifact_days": 14,
                "unreferenced_media_days": 30,
            }
        ],
    )

    op.create_table(
        "retention_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workflow_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_jobs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'previewed'"),
        ),
        sa.Column("preview_token", sa.Text(), nullable=False),
        sa.Column(
            "schema_revision",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'0009_operational_retention'"),
        ),
        sa.Column(
            "policy_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "candidate_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "cleanup_intent_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "count_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "error_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "previewed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("preview_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('previewed', 'queued', 'running', 'succeeded', 'partial', 'failed', 'expired')",
            name="ck_retention_run_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(policy_snapshot) = 'object'",
            name="ck_retention_run_policy_snapshot_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(candidate_snapshot) = 'array'",
            name="ck_retention_run_candidate_snapshot_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cleanup_intent_snapshot) = 'array'",
            name="ck_retention_run_cleanup_intent_snapshot_array",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(count_snapshot) = 'object'",
            name="ck_retention_run_count_snapshot_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(error_snapshot) = 'array'",
            name="ck_retention_run_error_snapshot_array",
        ),
        sa.CheckConstraint(
            "preview_expires_at > previewed_at",
            name="ck_retention_run_preview_expiry",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preview_token", name="uq_retention_runs_preview_token"),
        sa.UniqueConstraint("workflow_job_id", name="uq_retention_runs_workflow_job_id"),
    )
    op.create_index(
        "ix_retention_runs_status_created",
        "retention_runs",
        ["status", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_retention_runs_preview_expiry",
        "retention_runs",
        ["preview_expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'previewed'"),
    )


def downgrade() -> None:
    op.drop_index("ix_retention_runs_preview_expiry", table_name="retention_runs")
    op.drop_index("ix_retention_runs_status_created", table_name="retention_runs")
    op.drop_table("retention_runs")
    op.drop_table("retention_policies")
