"""add prompt governance activation and route policy

Revision ID: 0017_prompt_governance
Revises: 0016_llm_provider_settings
Create Date: 2026-07-24
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0017_prompt_governance"
down_revision: str | None = "0016_llm_provider_settings"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "prompt_template_versions",
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "prompt_template_versions",
        sa.Column("activated_by_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "prompt_template_versions",
        sa.Column("activated_by_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "prompt_template_versions",
        sa.Column("activation_reason", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE prompt_template_versions
            SET activated_at = created_at,
                activated_by_type = 'system',
                activated_by_id = 'migration',
                activation_reason = 'Backfilled active prompt during Phase 7 migration'
            WHERE is_active
            """
        )
    )
    op.create_index(
        "uq_prompt_template_versions_one_active",
        "prompt_template_versions",
        ["prompt_template_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_check_constraint(
        "ck_prompt_template_versions_active_metadata",
        "prompt_template_versions",
        "NOT is_active OR (activated_at IS NOT NULL AND activated_by_type IS NOT NULL "
        "AND activated_by_id IS NOT NULL AND activation_reason IS NOT NULL)",
    )
    op.add_column(
        "automation_routes",
        sa.Column(
            "prompt_policy",
            sa.Text(),
            server_default="pinned",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_automation_routes_prompt_policy",
        "automation_routes",
        "prompt_policy IN ('pinned', 'follow_active')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_automation_routes_prompt_policy",
        "automation_routes",
        type_="check",
    )
    op.drop_column("automation_routes", "prompt_policy")
    op.drop_constraint(
        "ck_prompt_template_versions_active_metadata",
        "prompt_template_versions",
        type_="check",
    )
    op.drop_index(
        "uq_prompt_template_versions_one_active",
        table_name="prompt_template_versions",
    )
    op.drop_column("prompt_template_versions", "activation_reason")
    op.drop_column("prompt_template_versions", "activated_by_id")
    op.drop_column("prompt_template_versions", "activated_by_type")
    op.drop_column("prompt_template_versions", "activated_at")
