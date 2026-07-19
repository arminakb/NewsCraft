from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


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


class QualifiedGenerationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    qualification_status: Literal["unqualified", "qualified"] = "unqualified"
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    max_attempts: int = Field(default=3, ge=1, le=3)
    max_pack_cost_usd: Decimal = Field(default=Decimal("2.00"), gt=Decimal("0"), le=Decimal("20"))
    max_elapsed_seconds: int = Field(default=180, ge=30, le=600)
    retryable_http_statuses: tuple[Literal[408, 429, 500, 502, 503, 504], ...] = (
        408,
        429,
        500,
        502,
        503,
        504,
    )
    automatic_model_fallback: Literal[False] = False

    @field_validator("retryable_http_statuses")
    @classmethod
    def require_exact_retry_classes(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if value != (408, 429, 500, 502, 503, 504):
            raise ValueError("qualified generation retry statuses are immutable")
        return value


class OpenRouterProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: HttpUrl = HttpUrl("https://openrouter.ai/api/v1")
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    http_referer: HttpUrl | None = None
    app_title: str = Field(default="NewsCraft", min_length=1, max_length=80)
    pricing: ProviderPricingSettings | None = None
    research_budgets: ResearchBudgetsSettings | None = None
    generation_policy: QualifiedGenerationPolicy | None = None


class CodexGenerationLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_model_calls: Literal[1] = 1
    max_input_tokens: int = Field(default=60_000, ge=1_000, le=500_000)
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    max_elapsed_seconds: int = Field(default=180, ge=10, le=600)


class CodexProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    research_budgets: ResearchBudgetsSettings | None = None
    generation_limits: CodexGenerationLimits = Field(default_factory=CodexGenerationLimits)


def default_research_budgets() -> ResearchBudgetsSettings:
    return ResearchBudgetsSettings(
        standard=ResearchBudgetSettings(
            max_model_calls=1,
            max_input_tokens=60_000,
            max_output_tokens=12_000,
            max_cost_usd=Decimal("0"),
            max_queries=4,
            max_results_per_query=5,
            max_pages=8,
            max_elapsed_seconds=180,
            max_total_chars=120_000,
        ),
        deep=ResearchBudgetSettings(
            max_model_calls=1,
            max_input_tokens=120_000,
            max_output_tokens=24_000,
            max_cost_usd=Decimal("0"),
            max_queries=8,
            max_results_per_query=10,
            max_pages=16,
            max_elapsed_seconds=300,
            max_total_chars=250_000,
        ),
    )


def default_codex_provider_settings() -> CodexProviderSettings:
    return CodexProviderSettings(
        research_budgets=default_research_budgets(),
        generation_limits=CodexGenerationLimits(),
    )


def effective_codex_provider_settings(value: CodexProviderSettings) -> CodexProviderSettings:
    defaults = default_codex_provider_settings()
    return value.model_copy(
        update={
            "research_budgets": value.research_budgets or defaults.research_budgets,
            "generation_limits": value.generation_limits,
        }
    )


__all__ = [
    "CodexGenerationLimits",
    "CodexProviderSettings",
    "OpenRouterProviderSettings",
    "ProviderPricingSettings",
    "QualifiedGenerationPolicy",
    "ResearchBudgetSettings",
    "ResearchBudgetsSettings",
    "default_codex_provider_settings",
    "default_research_budgets",
    "effective_codex_provider_settings",
    "merge_provider_settings",
]
