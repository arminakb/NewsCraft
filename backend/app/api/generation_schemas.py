from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.jobs.credential_capabilities import CapabilityStatus


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
                raise ValueError(f"Brand profile fields cannot be null: {', '.join(null_fields)}")
        return value


class PromptTemplateCreate(BaseModel):
    purpose_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class PromptTemplateVersionCreate(BaseModel):
    system_template: str = Field(min_length=1, max_length=20_000)
    user_template: str = Field(min_length=1, max_length=40_000)

    @model_validator(mode="after")
    def validate_combined_size(self):
        if len(self.system_template) + len(self.user_template) > 50_000:
            raise ValueError("combined prompt template size cannot exceed 50000 characters")
        return self


class PromptActivationCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PromptTemplateVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt_template_id: UUID
    version: int
    system_template: str
    user_template: str
    output_schema_version: str
    output_schema: dict
    checksum_sha256: str
    is_active: bool
    activated_at: datetime | None
    activated_by_type: str | None
    activated_by_id: str | None
    activation_reason: str | None
    created_at: datetime


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
    capabilities: dict[Literal["generation", "research"], bool]
    capability_states: dict[Literal["generation", "research"], CapabilityStatus]
    unavailability_codes: list[str]


__all__ = [
    "AIProviderProfileOut",
    "BrandProfileCreate",
    "BrandProfilePatch",
    "BrandProfileOut",
    "PromptTemplateVersionOut",
    "PromptActivationCreate",
]
