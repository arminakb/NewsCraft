from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.redaction import redact_secrets


def coerce_progress_count(value: object) -> int:
    """Normalize a stored progress counter to a plain non-null integer."""

    if value is None:
        return 0
    if isinstance(value, int | float | str | Decimal):
        return int(value)
    raise ValueError("progress counts must be numeric")


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
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_count: int | None = 0
    health_status: str | None = None
    last_http_status: int | None = None
    last_error_message: str | None = None
    last_parse_count: int | None = 0
    last_suitable_count: int | None = 0
    last_media_count: int | None = 0
    fetch_interval_minutes: int | None = 1440
    icon_url: str | None = None
    icon_source: str | None = None
    icon_updated_at: datetime | None = None
    icon_status: str | None = "pending"
    created_at: datetime | None = None


class SourceCreateIn(BaseModel):
    platform: Literal["rss", "atom", "telegram_public"]
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2_048)
    source_group: str = Field(default="general", min_length=1, max_length=100)
    language_hint: str = Field(default="en", min_length=2, max_length=16)
    fetch_interval_minutes: int = Field(default=30, ge=5, le=10_080)

    @field_validator("name", "source_group", "language_hint", "url")
    @classmethod
    def trim_source_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_source_url(self):
        if self.platform in {"rss", "atom"}:
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Feed URL must use http:// or https://")
            return self
        if telegram_username_from_url(self.url) is None:
            raise ValueError("Telegram URL must identify a public channel")
        return self


def telegram_username_from_url(value: str) -> str | None:
    candidate = value.strip()
    if candidate.startswith(("http://", "https://")):
        parsed = urlsplit(candidate)
        if parsed.hostname not in {"t.me", "www.t.me"}:
            return None
        candidate = parsed.path.strip("/").removeprefix("s/")
    candidate = candidate.removeprefix("@")
    if 5 <= len(candidate) <= 32 and candidate.replace("_", "").isalnum():
        return candidate
    return None


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
    byte_length: int | None = None
    created_at: datetime | None = None


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
    content_text: str | None = None
    content_html_sanitized: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    primary_source_id: UUID | None = None
    classification_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def derive_primary_media_flag(self) -> "ContentItemOut":
        # `MediaAsset.is_primary` is an asset-global column and a single asset row is
        # shared by every content item citing the same URL, so it cannot carry a
        # per-item decision. Derive the flag from the item being serialized instead.
        if self.primary_media is not None:
            self.primary_media.is_primary = True
        return self


class IngestRunRequest(BaseModel):
    request_id: UUID
    platforms: list[str] | None = None
    source_ids: list[str] | None = None


class IngestRunSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime
    finished_at: datetime | None = None
    trigger: str
    status: str
    stats: dict[str, Any] = Field(default_factory=dict)
    source_collection_id: UUID | None = None
    source_collection_name_at_start: str | None = None
    source_count: int = 0
    processed_count: int = 0
    success_count: int = 0
    failure_count: int = 0

    @field_validator("source_count", "processed_count", "success_count", "failure_count", mode="before")
    @classmethod
    def default_progress_counts(cls, value: object) -> int:
        return coerce_progress_count(value)

    @field_validator("stats", mode="before")
    @classmethod
    def redact_legacy_stats(cls, value: object) -> dict[str, Any]:
        redacted = redact_secrets(value)
        return redacted if isinstance(redacted, dict) else {}


class MediaAssetListOut(MediaAssetOut):
    pass


class SourceDetailOut(SourceOut):
    pass


class SourceHealthOut(BaseModel):
    source_id: UUID
    health_status: str
    is_checking: bool = False
    last_checked_at: datetime
    failure_reason: str | None = None


class ApproveContentItemIn(BaseModel):
    notes: str | None = None


class ApproveContentItemOut(BaseModel):
    id: UUID
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)
