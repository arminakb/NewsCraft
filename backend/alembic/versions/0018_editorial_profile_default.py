"""enforce one default editorial profile

Revision ID: 0018_editorial_profile_default
Revises: 0017_prompt_governance
Create Date: 2026-07-24
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0018_editorial_profile_default"
down_revision: str | None = "0017_prompt_governance"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            WITH ranked_defaults AS (
                SELECT id,
                       row_number() OVER (ORDER BY updated_at DESC, created_at DESC, id) AS position
                FROM brand_profiles
                WHERE is_default
            )
            UPDATE brand_profiles
            SET is_default = false
            WHERE id IN (
                SELECT id
                FROM ranked_defaults
                WHERE position > 1
            )
            """
        )
    )
    op.create_index(
        "uq_brand_profiles_one_default",
        "brand_profiles",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_brand_profiles_one_default",
        table_name="brand_profiles",
    )
