from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.telegram_schemas import SecretRef
from app.generation.provider_settings import (
    OpenRouterProviderSettings,
    ProviderPricingSettings,
    ResearchBudgetSettings,
    ResearchBudgetsSettings,
)


class BrandProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    output_language: str = Field(min_length=2, max_length=12)
    tone: str = Field(min_length=1, max_length=120)
    editorial_rules: list[str] = Field(default_factory=list, max_length=100)
    attribution_rules: dict = Field(default_factory=dict)
    default_hashtags: list[str] = Field(default_factory=list, max_length=50)
    platform_preferences: dict = Field(default_factory=dict)
    is_default: bool = False


class BrandProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    output_language: str | None = Field(default=None, min_length=2, max_length=12)
    tone: str | None = Field(default=None, min_length=1, max_length=120)
    editorial_rules: list[str] | None = Field(default=None, max_length=100)
    attribution_rules: dict | None = None
    default_hashtags: list[str] | None = Field(default=None, max_length=50)
    platform_preferences: dict | None = None
    is_default: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value):
        if isinstance(value, dict):
            null_fields = sorted(key for key, item in value.items() if item is None)
            if null_fields:
                raise ValueError(
                    f"Brand profile fields cannot be null: {', '.join(null_fields)}"
                )
        return value


class PromptTemplateCreate(BaseModel):
    purpose_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class PromptTemplateVersionCreate(BaseModel):
    system_template: str = Field(min_length=1)
    user_template: str = Field(min_length=1)


class AIProviderProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider_type: Literal["fake", "openrouter"]
    default_model: str | None = Field(default=None, min_length=1, max_length=200)
    secret_ref: SecretRef | None = None
    settings: OpenRouterProviderSettings | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_provider_contract(self):
        if self.provider_type == "fake":
            if self.secret_ref is not None or self.settings is not None:
                raise ValueError("fake provider cannot have secret or provider settings")
        elif self.secret_ref is None or self.default_model is None:
            raise ValueError("openrouter requires secret_ref and default_model")
        return self


class AIProviderProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    default_model: str | None = Field(default=None, min_length=1, max_length=200)
    secret_ref: SecretRef | None = None
    settings: dict | None = None
    enabled: bool | None = None


class BrandProfileOut(BrandProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class AIProviderProfileOut(BaseModel):
    id: UUID
    name: str
    provider_type: str
    default_model: str | None
    settings: dict
    enabled: bool
    configured: bool


__all__ = [
    "AIProviderProfileCreate",
    "AIProviderProfilePatch",
    "AIProviderProfileOut",
    "BrandProfileCreate",
    "BrandProfilePatch",
    "BrandProfileOut",
    "OpenRouterProviderSettings",
    "ProviderPricingSettings",
    "ResearchBudgetSettings",
    "ResearchBudgetsSettings",
]
