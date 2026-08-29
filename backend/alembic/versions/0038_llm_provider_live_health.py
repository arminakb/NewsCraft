"""persist live LLM provider test diagnostics

Revision ID: 0038_llm_provider_live_health
Revises: 0037_wave2a_ops
"""

import sqlalchemy as sa

from alembic import op

revision = "0038_llm_provider_live_health"
down_revision = "0037_wave2a_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_providers", sa.Column("failure_message", sa.Text(), nullable=True))
    op.add_column(
        "llm_providers",
        sa.Column("last_successful_test_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("llm_providers", sa.Column("last_test_latency_ms", sa.Integer(), nullable=True))
    op.add_column("llm_providers", sa.Column("last_tested_model", sa.Text(), nullable=True))

    op.drop_constraint("ck_llm_providers_health_status", "llm_providers", type_="check")
    op.create_check_constraint(
        "ck_llm_providers_health_status",
        "llm_providers",
        "health_status IN ('unchecked', 'healthy', 'degraded', 'unhealthy')",
    )
    op.create_check_constraint(
        "ck_llm_providers_last_test_latency_ms",
        "llm_providers",
        "last_test_latency_ms IS NULL OR last_test_latency_ms >= 0",
    )
    op.execute(
        """
        UPDATE llm_providers
        SET last_successful_test_at = last_checked_at,
            last_tested_model = default_model
        WHERE health_status = 'healthy' AND last_checked_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_providers_last_test_latency_ms", "llm_providers", type_="check")
    op.drop_constraint("ck_llm_providers_health_status", "llm_providers", type_="check")
    op.create_check_constraint(
        "ck_llm_providers_health_status",
        "llm_providers",
        "health_status IN ('unchecked', 'healthy', 'unhealthy')",
    )
    op.drop_column("llm_providers", "last_tested_model")
    op.drop_column("llm_providers", "last_test_latency_ms")
    op.drop_column("llm_providers", "last_successful_test_at")
    op.drop_column("llm_providers", "failure_message")
