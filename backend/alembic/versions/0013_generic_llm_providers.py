"""add generic LLM provider connections

Revision ID: 0013_generic_llm_providers
Revises: 0012_security_foundation
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_generic_llm_providers"
down_revision: str | None = "0012_security_foundation"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


_DEFAULT_RESEARCH_BUDGETS = """{
  "standard": {
    "max_model_calls": 1, "max_input_tokens": 60000, "max_output_tokens": 12000,
    "max_cost_usd": "0", "max_queries": 4, "max_results_per_query": 5,
    "max_pages": 8, "max_elapsed_seconds": 180, "max_total_chars": 120000
  },
  "deep": {
    "max_model_calls": 1, "max_input_tokens": 120000, "max_output_tokens": 24000,
    "max_cost_usd": "0", "max_queries": 8, "max_results_per_query": 10,
    "max_pages": 16, "max_elapsed_seconds": 300, "max_total_chars": 250000
  }
}"""


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("protocol", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("default_model", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),  # noqa: E501
        sa.Column("health_status", sa.Text(), server_default="unchecked", nullable=False),
        sa.Column("generation_capability", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("research_capability", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ownership", sa.Text(), server_default="operator_managed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("protocol IN ('openai_compatible', 'fake')", name="ck_llm_providers_protocol"),
        sa.CheckConstraint(
            "health_status IN ('unchecked', 'healthy', 'unhealthy')",
            name="ck_llm_providers_health_status",
        ),
        sa.CheckConstraint(
            "generation_capability IN ('unknown', 'ready', 'unavailable')",
            name="ck_llm_providers_generation_capability",
        ),
        sa.CheckConstraint(
            "research_capability IN ('unknown', 'ready', 'unavailable')",
            name="ck_llm_providers_research_capability",
        ),
        sa.CheckConstraint(
            "ownership IN ('system_managed', 'operator_managed')",
            name="ck_llm_providers_ownership",
        ),
        sa.CheckConstraint(
            "(protocol = 'fake' AND base_url IS NULL AND secret_id IS NULL) OR "
            "(protocol = 'openai_compatible' AND base_url IS NOT NULL)",
            name="ck_llm_providers_protocol_shape",
        ),
        sa.ForeignKeyConstraint(["secret_id"], ["encrypted_secrets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_llm_providers_name"),
        sa.UniqueConstraint("secret_id", name="uq_llm_providers_secret_id"),
    )
    op.create_index("ix_llm_providers_enabled_name", "llm_providers", ["enabled", "name"])

    budgets = _DEFAULT_RESEARCH_BUDGETS.replace("'", "''")
    op.execute(
        sa.text(
            f"""
            INSERT INTO llm_providers (
                id, name, protocol, base_url, default_model, enabled, secret_id,
                settings, health_status, generation_capability, research_capability,
                failure_code, ownership, created_at, updated_at
            )
            SELECT
                id,
                name,
                CASE WHEN provider_type = 'fake' THEN 'fake' ELSE 'openai_compatible' END,
                CASE WHEN provider_type = 'fake' THEN NULL
                     ELSE rtrim(COALESCE(settings->>'base_url', 'https://openrouter.ai/api/v1'), '/') END,
                COALESCE(
                    NULLIF(default_model, ''),
                    CASE WHEN provider_type = 'fake' THEN 'fake-v1' ELSE 'unconfigured' END
                ),
                CASE WHEN provider_type = 'fake' THEN enabled ELSE false END,
                NULL,
                CASE WHEN provider_type = 'fake' THEN '{{}}'::jsonb ELSE
                    jsonb_build_object(
                        'timeout_seconds', COALESCE((settings->>'timeout_seconds')::integer, 60),
                        'max_input_tokens', 60000,
                        'max_output_tokens', 12000,
                        'pricing', COALESCE(
                            settings->'pricing',
                            '{{"input_usd_per_million":"0","output_usd_per_million":"0"}}'::jsonb
                        ),
                        'research_budgets', COALESCE(settings->'research_budgets', '{budgets}'::jsonb),
                        'attribution_headers', jsonb_build_object(
                            'http_referer', settings->'http_referer',
                            'app_title', COALESCE(settings->>'app_title', 'NewsCraft')
                        )
                    )
                END,
                CASE WHEN provider_type = 'fake' AND enabled THEN 'healthy' ELSE 'unchecked' END,
                CASE WHEN provider_type = 'fake' AND enabled THEN 'ready' ELSE 'unavailable' END,
                CASE WHEN provider_type = 'fake' AND enabled THEN 'ready' ELSE 'unavailable' END,
                CASE WHEN provider_type = 'fake' AND enabled THEN NULL
                     WHEN provider_type = 'fake' THEN 'disabled'
                     ELSE 'credential_import_required' END,
                'operator_managed',
                created_at,
                updated_at
            FROM ai_provider_profiles
            WHERE provider_type IN ('fake', 'openrouter')
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_llm_providers_enabled_name", table_name="llm_providers")
    op.drop_table("llm_providers")
