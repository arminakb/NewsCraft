"""Add durable Automation run idempotency.

Revision ID: 0028_automation_execution
Revises: 0027_versioned_automations
"""

import sqlalchemy as sa

from alembic import op

revision = "0028_automation_execution"
down_revision = "0027_versioned_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("automation_runs", sa.Column("idempotency_key", sa.Text(), nullable=True))
    op.add_column("automation_runs", sa.Column("request_hash", sa.Text(), nullable=True))
    op.execute(
        "UPDATE automation_runs SET idempotency_key = 'legacy-run:' || id::text, "
        "request_hash = repeat('0', 64) WHERE idempotency_key IS NULL"
    )
    op.alter_column("automation_runs", "idempotency_key", nullable=False)
    op.alter_column("automation_runs", "request_hash", nullable=False)
    op.create_unique_constraint("uq_automation_runs_idempotency_key", "automation_runs", ["idempotency_key"])
    op.create_check_constraint(
        "ck_automation_runs_request_hash", "automation_runs", "char_length(request_hash) = 64"
    )


def downgrade() -> None:
    op.drop_constraint("ck_automation_runs_request_hash", "automation_runs", type_="check")
    op.drop_constraint("uq_automation_runs_idempotency_key", "automation_runs", type_="unique")
    op.drop_column("automation_runs", "request_hash")
    op.drop_column("automation_runs", "idempotency_key")
