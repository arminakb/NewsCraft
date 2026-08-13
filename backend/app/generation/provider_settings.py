from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

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


class ProviderShapeError(ValueError):
    """A provider profile does not satisfy the shape its provider type requires."""


class UnsupportedProviderTypeError(ProviderShapeError):
    """The provider profile names a provider type this build cannot execute."""


@dataclass(frozen=True, slots=True)
class ValidatedProviderShape:
    """The one parsed answer to "is this profile usable for its provider type?"."""

    provider_type: str
    model: str
    codex: CodexProviderSettings | None = None
    openrouter: OpenRouterProviderSettings | None = None


def validate_provider_shape(
    *,
    provider_type: str,
    default_model: str | None,
    secret_ref: str | None,
    settings: Mapping[str, Any] | None,
    model_override: str | None = None,
    setting_defaults: Mapping[str, Any] | None = None,
) -> ValidatedProviderShape:
    """Validate a provider profile's secret/model/settings shape for its provider type.

    This is the single definition of what each ``provider_type`` requires. Callers
    translate :class:`ProviderShapeError` into their own error taxonomy and layer
    their own extra requirements (transport wiring, research budgets) on top of the
    returned, already-parsed settings.
    """

    model = model_override or default_model
    raw = dict(settings or {})
    if provider_type == "fake":
        if secret_ref is not None or raw:
            raise ProviderShapeError("Fake provider profile has invalid settings")
        return ValidatedProviderShape(provider_type="fake", model=model or "fake-v1")
    if provider_type == "codex":
        if secret_ref is not None:
            raise ProviderShapeError("Codex provider profile cannot have a secret reference")
        if not model:
            raise ProviderShapeError("Selected provider profile has no model")
        try:
            codex = effective_codex_provider_settings(CodexProviderSettings.model_validate(raw))
        except TypeError, ValueError:
            raise ProviderShapeError("Selected provider profile settings are invalid") from None
        return ValidatedProviderShape(provider_type="codex", model=model, codex=codex)
    if provider_type == "openrouter":
        if not model:
            raise ProviderShapeError("Selected provider profile has no model")
        if not secret_ref:
            raise ProviderShapeError("Selected provider profile has no secret reference")
        try:
            openrouter = OpenRouterProviderSettings.model_validate({**dict(setting_defaults or {}), **raw})
        except TypeError, ValueError:
            raise ProviderShapeError("Selected provider profile settings are invalid") from None
        return ValidatedProviderShape(provider_type="openrouter", model=model, openrouter=openrouter)
    raise UnsupportedProviderTypeError("Selected provider type is unsupported")


__all__ = [
    "CodexGenerationLimits",
    "CodexProviderSettings",
    "OpenRouterProviderSettings",
    "ProviderPricingSettings",
    "ProviderShapeError",
    "QualifiedGenerationPolicy",
    "ResearchBudgetSettings",
    "ResearchBudgetsSettings",
    "UnsupportedProviderTypeError",
    "ValidatedProviderShape",
    "default_codex_provider_settings",
    "default_research_budgets",
    "effective_codex_provider_settings",
    "merge_provider_settings",
    "validate_provider_shape",
]
