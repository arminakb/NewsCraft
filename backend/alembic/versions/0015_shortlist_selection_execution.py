"""scope shortlist rows to a selection execution

Revision ID: 0015_shortlist_selection_execution
Revises: 0014_artifact_idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_shortlist_selection_execution"
down_revision: str | None = "0014_artifact_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_shortlists",
        sa.Column("selection_execution_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        sa.text(
            r"""
            WITH ordered AS (
                SELECT
                    id,
                    request_id,
                    content_item_id,
                    rank,
                    created_at,
                    lag(rank) OVER (
                        PARTITION BY request_id ORDER BY created_at, id
                    ) AS previous_rank
                FROM candidate_shortlists
            ),
            grouped AS (
                SELECT
                    *,
                    sum(
                        CASE WHEN previous_rank IS NULL OR rank <= previous_rank THEN 1 ELSE 0 END
                    ) OVER (
                        PARTITION BY request_id ORDER BY created_at, id
                    ) AS execution_number
                FROM ordered
            ),
            disambiguated AS (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY request_id, execution_number, content_item_id
                        ORDER BY created_at, id
                    ) AS duplicate_number
                FROM grouped
            )
            UPDATE candidate_shortlists AS shortlist
            SET selection_execution_id = md5(
                disambiguated.request_id::text
                || '\:legacy_selection\:'
                || disambiguated.execution_number::text
                || CASE
                    WHEN disambiguated.duplicate_number = 1 THEN ''
                    ELSE '\:ambiguous_row\:' || disambiguated.id::text
                END
            )::uuid
            FROM disambiguated
            WHERE shortlist.id = disambiguated.id
            """
        )
    )
    op.alter_column("candidate_shortlists", "selection_execution_id", nullable=False)
    op.create_index(
        "ix_candidate_shortlists_request_execution",
        "candidate_shortlists",
        ["request_id", "selection_execution_id"],
    )
    op.create_unique_constraint(
        "uq_candidate_shortlists_execution_content_item",
        "candidate_shortlists",
        ["selection_execution_id", "content_item_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_candidate_shortlists_execution_content_item",
        "candidate_shortlists",
        type_="unique",
    )
    op.drop_index("ix_candidate_shortlists_request_execution", table_name="candidate_shortlists")
    op.drop_column("candidate_shortlists", "selection_execution_id")
