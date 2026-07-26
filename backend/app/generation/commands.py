from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.generation.platform_schemas import Platform
from app.generation.telegram_schema import TelegramRewriteOutput


class GeneratePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_profile_id: UUID | None = None
    platforms: list[Platform] = Field(min_length=1)
    generation_provider_profile_id: UUID
    research_mode: Literal["off", "manual", "auto_if_incomplete"] = "off"
    research_provider_profile_id: UUID | None = None
    research_run_id: UUID | None = None


class EditVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision_id: UUID
    base_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: TelegramRewriteOutput
    media_asset_ids: list[UUID]
    edit_note: str = Field(min_length=1, max_length=500)


class RegenerateVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_provider_profile_id: UUID
    instruction: str | None = Field(default=None, max_length=1_000)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)
