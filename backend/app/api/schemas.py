from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    name: str
    feed_url: str | None = None
    homepage_url: str | None = None
    telegram_username: str | None = None
    source_group: str
    language_hint: str | None = None
    active: bool
    last_fetch_at: datetime | None = None


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    normalized_url: str
    kind: str
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    storage_path: str | None = None
    fetch_status: str | None = None
    media_quality: str | None = None
    media_confidence: Decimal | None = None
    is_primary_candidate: bool | None = None
    is_primary: bool | None = None
    media_source_type: str | None = None
    asset_role: str | None = None


class ContentItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_type: str
    title: str | None = None
    summary: str | None = None
    canonical_url: str | None = None
    language_code: str | None = None
    direction: str | None = None
    status: str
    score: int = 0
    tags: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    sort_at: datetime
    primary_image_id: UUID | None = None
    primary_media: MediaAssetOut | None = None
    content_type: str | None = None
    rewrite_bucket: str | None = None
    is_rewrite_ready: bool | None = None
    rewrite_ready_reason: str | None = None
    rewrite_blockers: list[str] = Field(default_factory=list)
    classification_reasons: list[str] = Field(default_factory=list)
    source_tier: str | None = None
    freshness_bucket: str | None = None
    quality_status: str | None = None
    score_breakdown: dict[str, Any] = Field(default_factory=dict)


class IngestRunRequest(BaseModel):
    platforms: list[str] | None = None
    source_ids: list[str] | None = None


class IngestRunOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    checked: int = 0
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    items: int = 0
    media_candidates: int = 0
    errors: list[dict] = []


class DiagnosticsOut(BaseModel):
    status: str
    checks: dict[str, str]
    source_health: dict[str, int] = Field(default_factory=dict)
    problem_sources: list[dict[str, Any]] = Field(default_factory=list)


class ApproveContentItemIn(BaseModel):
    notes: str | None = None


class ApproveContentItemOut(BaseModel):
    id: UUID
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)
