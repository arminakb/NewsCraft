"""use command-derived artifact identities

Revision ID: 0014_artifact_idempotency
Revises: 0013_agent_step_run_request_tracing
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_artifact_idempotency"
down_revision: str | None = "0013_agent_step_run_request_tracing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_candidate_shortlists_request_content_item",
        "candidate_shortlists",
        type_="unique",
    )
    op.create_index(
        "ix_candidate_shortlists_request_content_item",
        "candidate_shortlists",
        ["request_id", "content_item_id"],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM candidate_shortlists duplicate
            USING candidate_shortlists canonical
            WHERE duplicate.request_id = canonical.request_id
              AND duplicate.content_item_id = canonical.content_item_id
              AND (duplicate.created_at, duplicate.id) > (canonical.created_at, canonical.id)
            """
        )
    )
    op.drop_index("ix_candidate_shortlists_request_content_item", table_name="candidate_shortlists")
    op.create_unique_constraint(
        "uq_candidate_shortlists_request_content_item",
        "candidate_shortlists",
        ["request_id", "content_item_id"],
    )
