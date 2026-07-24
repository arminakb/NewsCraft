from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator, model_validator

from app.generation.provider_settings import (
    ProviderPricingSettings,
    ResearchBudgetsSettings,
    default_research_budgets,
)


class AttributionHeaders(BaseModel):
    model_config = ConfigDict(extra="forbid")

    http_referer: HttpUrl | None = None
    app_title: str = Field(default="NewsCraft", min_length=1, max_length=80)


def _zero_pricing() -> ProviderPricingSettings:
    return ProviderPricingSettings(
        input_usd_per_million=Decimal("0"),
        output_usd_per_million=Decimal("0"),
    )


class LLMProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: int = Field(default=60, ge=1, le=300)
    max_input_tokens: int = Field(default=60_000, ge=1_000, le=500_000)
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    research_budgets: ResearchBudgetsSettings = Field(default_factory=default_research_budgets)
    pricing: ProviderPricingSettings = Field(default_factory=_zero_pricing)
    attribution_headers: AttributionHeaders = Field(default_factory=AttributionHeaders)


def effective_llm_provider_settings(value: Mapping[str, object]) -> LLMProviderSettings:
    """Apply current defaults to legacy persisted settings that stored JSON nulls."""

    normalized = dict(value)
    defaults = LLMProviderSettings()
    if normalized.get("research_budgets") is None:
        normalized["research_budgets"] = defaults.research_budgets.model_dump(mode="json")
    if normalized.get("pricing") is None:
        normalized["pricing"] = defaults.pricing.model_dump(mode="json")
    return LLMProviderSettings.model_validate(normalized)


class LLMProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    protocol: Literal["openai_compatible", "fake"] = "openai_compatible"
    base_url: HttpUrl | None = None
    default_model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=65_536)
    settings: LLMProviderSettings = Field(default_factory=LLMProviderSettings)
    enabled: bool = False

    @field_validator("name", "default_model")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_protocol_shape(self):
        if self.protocol == "fake":
            if self.base_url is not None or self.api_key is not None:
                raise ValueError("fake provider forbids base_url and api_key")
            return self
        if self.base_url is None or self.api_key is None:
            raise ValueError("openai_compatible requires base_url and api_key")
        if (
            self.base_url.scheme != "https"
            or self.base_url.username is not None
            or self.base_url.password is not None
            or self.base_url.query is not None
            or self.base_url.fragment is not None
        ):
            raise ValueError("base_url must be a credential-free HTTPS URL")
        return self


class LLMProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: HttpUrl | None = None
    default_model: str | None = Field(default=None, min_length=1, max_length=200)
    settings: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("provider patch fields cannot be null")
        return value


class LLMProviderOut(BaseModel):
    id: UUID
    name: str
    protocol: Literal["openai_compatible", "fake"]
    base_url: str | None
    default_model: str
    enabled: bool
    configured: bool
    settings: LLMProviderSettings
    health_status: Literal["unchecked", "healthy", "unhealthy"]
    generation_capability: Literal["unknown", "ready", "unavailable"]
    research_capability: Literal["unknown", "ready", "unavailable"]
    generation_ready: bool
    research_ready: bool
    failure_code: str | None
    last_checked_at: datetime | None
    ownership: Literal["system_managed", "operator_managed"]
    created_at: datetime
    updated_at: datetime


class LLMProviderDependenciesOut(BaseModel):
    automations: int
    generation_runs: int
    research_runs: int
    active_jobs: int
    blocked: bool


__all__ = [
    "AttributionHeaders",
    "LLMProviderCreate",
    "LLMProviderDependenciesOut",
    "LLMProviderOut",
    "LLMProviderPatch",
    "LLMProviderSettings",
    "effective_llm_provider_settings",
]
