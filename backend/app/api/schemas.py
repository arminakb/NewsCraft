from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
    sort_at: datetime
    primary_image_id: UUID | None = None
    primary_media: MediaAssetOut | None = None


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
