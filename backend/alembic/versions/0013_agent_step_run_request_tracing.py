"""allow request-level agent step tracing

Revision ID: 0013_agent_step_run_request_tracing
Revises: 0012_telegram_dispatch_requests
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_agent_step_run_request_tracing"
down_revision: str | None = "0012_telegram_dispatch_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("agent_step_runs", "production_run_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # Request-level traces have no valid pre-0013 representation. Remove them
    # explicitly so restoring the historical NOT NULL constraint is deterministic.
    op.execute(sa.text("DELETE FROM agent_step_runs WHERE production_run_id IS NULL"))
    op.alter_column("agent_step_runs", "production_run_id", existing_type=sa.UUID(), nullable=False)
