"""repair legacy null LLM provider settings

Revision ID: 0016_llm_provider_settings
Revises: 0015_codex_gateway
Create Date: 2026-07-24
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0016_llm_provider_settings"
down_revision: str | None = "0015_codex_gateway"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


_DEFAULT_PRICING = """{
  "input_usd_per_million": "0",
  "output_usd_per_million": "0"
}"""

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
    pricing = _DEFAULT_PRICING.replace("'", "''")
    budgets = _DEFAULT_RESEARCH_BUDGETS.replace("'", "''")
    op.execute(
        sa.text(
            f"""
            UPDATE llm_providers
            SET settings = settings || jsonb_build_object(
                'pricing',
                CASE
                    WHEN jsonb_typeof(settings->'pricing') = 'object' THEN settings->'pricing'
                    ELSE '{pricing}'::jsonb
                END,
                'research_budgets',
                CASE
                    WHEN jsonb_typeof(settings->'research_budgets') = 'object'
                        THEN settings->'research_budgets'
                    ELSE '{budgets}'::jsonb
                END
            )
            WHERE protocol = 'openai_compatible'
              AND (
                  jsonb_typeof(settings->'pricing') IS DISTINCT FROM 'object'
                  OR jsonb_typeof(settings->'research_budgets') IS DISTINCT FROM 'object'
              )
            """
        )
    )
    op.create_check_constraint(
        "ck_llm_providers_required_settings",
        "llm_providers",
        "protocol != 'openai_compatible' OR ("
        "COALESCE(jsonb_typeof(settings->'pricing') = 'object', false) AND "
        "COALESCE(jsonb_typeof(settings->'research_budgets') = 'object', false))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_llm_providers_required_settings",
        "llm_providers",
        type_="check",
    )
