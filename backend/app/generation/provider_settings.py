from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


def merge_provider_settings(base: dict, patch: dict) -> dict:
    """Recursively merge a safe partial provider mapping without dropping sibling settings."""

    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_provider_settings(result[key], value)
        else:
            result[key] = value
    return result


class ProviderPricingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_usd_per_million: Decimal = Field(ge=Decimal("0"))
    output_usd_per_million: Decimal = Field(ge=Decimal("0"))


class ResearchBudgetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_model_calls: int = Field(default=6, ge=1, le=12)
    max_input_tokens: int = Field(default=60_000, ge=1_000, le=500_000)
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    max_cost_usd: Decimal = Field(default=Decimal("2.00"), ge=Decimal("0"), le=Decimal("50"))
    max_queries: int = Field(default=4, ge=1, le=8)
    max_results_per_query: int = Field(default=5, ge=1, le=10)
    max_pages: int = Field(default=8, ge=1, le=16)
    max_elapsed_seconds: int = Field(default=120, ge=10, le=600)
    max_total_chars: int = Field(default=120_000, ge=10_000, le=500_000)


class ResearchBudgetsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    standard: ResearchBudgetSettings
    deep: ResearchBudgetSettings


class OpenRouterProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: HttpUrl = HttpUrl("https://openrouter.ai/api/v1")
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    http_referer: HttpUrl | None = None
    app_title: str = Field(default="NewsCraft", min_length=1, max_length=80)
    pricing: ProviderPricingSettings | None = None
    research_budgets: ResearchBudgetsSettings | None = None
