"""add immutable automation dispatch creation sequence

Revision ID: 0007_dispatch_creation_sequence
Revises: 0006_telegram_automation_vertical
Create Date: 2026-07-13
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0007_dispatch_creation_sequence"
down_revision: str | None = "0006_telegram_automation_vertical"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

DISPATCH_SEQUENCE_NAME = "automation_dispatch_creation_sequence_seq"
dispatch_creation_sequence = sa.Sequence("automation_dispatch_creation_sequence_seq")


def upgrade() -> None:
    dispatch_creation_sequence.create(op.get_bind())
    op.add_column(
        "automation_dispatches",
        sa.Column(
            "creation_sequence",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id, row_number() OVER (ORDER BY created_at, id) AS creation_sequence
                FROM automation_dispatches
            )
            UPDATE automation_dispatches AS dispatch
            SET creation_sequence = ranked.creation_sequence
            FROM ranked
            WHERE dispatch.id = ranked.id
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            SELECT setval(
                '{DISPATCH_SEQUENCE_NAME}',
                COALESCE((SELECT MAX(creation_sequence) FROM automation_dispatches), 0) + 1,
                false
            )
            """
        )
    )
    op.execute(sa.text(f"ALTER SEQUENCE {DISPATCH_SEQUENCE_NAME} OWNED BY automation_dispatches.creation_sequence"))
    op.alter_column(
        "automation_dispatches",
        "creation_sequence",
        nullable=False,
        server_default=sa.text(f"nextval('{DISPATCH_SEQUENCE_NAME}')"),
    )
    op.create_unique_constraint(
        "uq_automation_dispatch_creation_sequence",
        "automation_dispatches",
        ["creation_sequence"],
    )
    op.create_index(
        "ix_automation_dispatch_route_sequence",
        "automation_dispatches",
        ["route_id", sa.text("creation_sequence DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automation_dispatch_route_sequence",
        table_name="automation_dispatches",
    )
    op.drop_constraint(
        "uq_automation_dispatch_creation_sequence",
        "automation_dispatches",
        type_="unique",
    )
    op.alter_column(
        "automation_dispatches",
        "creation_sequence",
        server_default=None,
    )
    op.execute(sa.text(f"ALTER SEQUENCE {DISPATCH_SEQUENCE_NAME} OWNED BY NONE"))
    op.drop_column("automation_dispatches", "creation_sequence")
    dispatch_creation_sequence.drop(op.get_bind())
