"""add content production workflow foundation

Revision ID: 0004_content_production_foundation
Revises: 0003_content_intelligence_schema
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_content_production_foundation"
down_revision = "0003_content_intelligence_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic creates version_num as VARCHAR(32); this and later descriptive revisions are longer.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_table(
        "content_production_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), server_default="telegram", nullable=False),
        sa.Column("language", sa.Text(), server_default="fa", nullable=False),
        sa.Column("tone", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("max_candidates", sa.Integer(), server_default="10", nullable=False),
        sa.Column("require_rewrite_ready", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("require_media", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.Text(), server_default="created", nullable=False),
        sa.Column(
            "constraints_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_content_production_requests_status",
        "content_production_requests",
        ["status", sa.text("created_at DESC")],
    )

    op.create_table(
        "candidate_shortlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(), server_default="0", nullable=False),
        sa.Column(
            "selection_reason_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "risk_flags_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("approval_status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["content_production_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "content_item_id", name="uq_candidate_shortlists_request_content_item"),
    )
    op.create_index("ix_candidate_shortlists_approval_status", "candidate_shortlists", ["approval_status"])
    op.create_index("ix_candidate_shortlists_request_rank", "candidate_shortlists", ["request_id", "rank"])

    op.create_table(
        "content_production_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.Text(), server_default="telegram", nullable=False),
        sa.Column("state", sa.Text(), server_default="created", nullable=False),
        sa.Column("current_step", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"]),
        sa.ForeignKeyConstraint(["request_id"], ["content_production_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_production_runs_request", "content_production_runs", ["request_id"])
    op.create_index("ix_content_production_runs_state_step", "content_production_runs", ["state", "current_step"])

    op.create_table(
        "agent_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column(
            "input_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "output_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="started", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column(
            "token_usage_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_step_runs_production_run", "agent_step_runs", ["production_run_id"])
    op.create_index("ix_agent_step_runs_step_status", "agent_step_runs", ["step_name", "status"])

    op.create_table(
        "workflow_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_workflow_events_aggregate",
        "workflow_events",
        ["aggregate_type", "aggregate_id", sa.text("occurred_at")],
    )
    op.create_index(
        "ix_workflow_events_correlation",
        "workflow_events",
        ["correlation_id", sa.text("occurred_at")],
    )
    op.create_index("ix_workflow_events_status_available", "workflow_events", ["status", "available_at"])


def downgrade() -> None:
    op.drop_index("ix_workflow_events_status_available", table_name="workflow_events")
    op.drop_index("ix_workflow_events_correlation", table_name="workflow_events")
    op.drop_index("ix_workflow_events_aggregate", table_name="workflow_events")
    op.drop_table("workflow_events")

    op.drop_index("ix_agent_step_runs_step_status", table_name="agent_step_runs")
    op.drop_index("ix_agent_step_runs_production_run", table_name="agent_step_runs")
    op.drop_table("agent_step_runs")

    op.drop_index("ix_content_production_runs_state_step", table_name="content_production_runs")
    op.drop_index("ix_content_production_runs_request", table_name="content_production_runs")
    op.drop_table("content_production_runs")

    op.drop_index("ix_candidate_shortlists_request_rank", table_name="candidate_shortlists")
    op.drop_index("ix_candidate_shortlists_approval_status", table_name="candidate_shortlists")
    op.drop_table("candidate_shortlists")

    op.drop_index("ix_content_production_requests_status", table_name="content_production_requests")
    op.drop_table("content_production_requests")
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
