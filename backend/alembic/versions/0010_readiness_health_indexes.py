"""add bounded operational-health queue index

Revision ID: 0010_readiness_health_indexes
Revises: 0009_operational_retention
Create Date: 2026-07-17
"""

from alembic import op

revision: str = "0010_readiness_health_indexes"
down_revision: str | None = "0009_operational_retention"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_workflow_jobs_operational_health",
        "workflow_jobs",
        ["job_type", "status", "scheduled_for"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_jobs_operational_health",
        table_name="workflow_jobs",
    )
