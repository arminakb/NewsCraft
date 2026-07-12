from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    last_parse_count: int | None = 0
    last_suitable_count: int | None = 0
    last_media_count: int | None = 0
    fetch_interval_minutes: int | None = 1440
    created_at: datetime | None = None


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


class DashboardSummaryOut(BaseModel):
    rss_feeds: int = 0
    telegram_channels: int = 0
    content_items: int = 0
    media_assets: int = 0
    warnings: int = 0


class IngestRunSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    started_at: datetime
    finished_at: datetime | None = None
    trigger: str
    status: str
    stats: dict[str, Any] = Field(default_factory=dict)


class MediaAssetListOut(MediaAssetOut):
    pass


class SourceDetailOut(SourceOut):
    pass


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


class ContentProductionRequestCreateIn(BaseModel):
    topic: str | None = None
    platform: str = "telegram"
    language: str = "fa"
    tone: str | None = None
    audience: str | None = None
    max_candidates: int = Field(default=10, ge=1, le=50)
    require_rewrite_ready: bool = True
    require_media: bool = False
    constraints_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None


class ContentProductionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic: str | None = None
    platform: str
    language: str
    tone: str | None = None
    audience: str | None = None
    max_candidates: int
    require_rewrite_ready: bool
    require_media: bool
    status: str
    constraints_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CandidateShortlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    selection_execution_id: UUID
    content_item_id: UUID
    rank: int
    score: Decimal
    selection_reason_json: dict[str, Any] = Field(default_factory=dict)
    risk_flags_json: list[str] = Field(default_factory=list)
    source_snapshot_json: dict[str, Any] = Field(default_factory=dict)
    approval_status: str
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    created_at: datetime | None = None


class ShortlistDecisionIn(BaseModel):
    selection_execution_id: UUID
    content_item_ids: list[UUID] = Field(min_length=1)

    @field_validator("content_item_ids")
    @classmethod
    def canonicalize_candidate_ids(cls, values: list[UUID]) -> list[UUID]:
        if len(set(values)) != len(values):
            raise ValueError("content_item_ids must not contain duplicates")
        return sorted(values, key=lambda value: value.int)


class ContentProductionRequestDetailOut(ContentProductionRequestOut):
    shortlist: list[CandidateShortlistOut] = Field(default_factory=list)


class ContentProductionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    content_item_id: UUID
    platform: str
    state: str
    current_step: str | None = None
    failure_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class EditorialBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    production_run_id: UUID
    angle: str
    key_facts_json: list[dict[str, Any]] = Field(default_factory=list)
    source_claims_json: list[dict[str, Any]] = Field(default_factory=list)
    unsafe_or_unverified_claims_json: list[dict[str, Any]] = Field(default_factory=list)
    audience: str | None = None
    tone: str | None = None
    do_not_say_json: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class TelegramDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    production_run_id: UUID
    brief_id: UUID
    draft_text: str
    title: str | None = None
    hashtags_json: list[str] = Field(default_factory=list)
    source_links_json: list[str] = Field(default_factory=list)
    warnings_json: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DraftQualityReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    production_run_id: UUID
    draft_id: UUID
    status: str
    score: Decimal
    factuality_warnings_json: list[str] = Field(default_factory=list)
    unsupported_claims_json: list[str] = Field(default_factory=list)
    style_warnings_json: list[str] = Field(default_factory=list)
    required_revisions_json: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class VisualBriefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    production_run_id: UUID
    status: str
    selected_media_asset_id: UUID | None = None
    needs_generation: bool
    visual_prompt: str | None = None
    visual_style: str | None = None
    provider_name: str | None = None
    provider_request_json: dict[str, Any] = Field(default_factory=dict)
    provider_result_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TelegramPostPackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    production_run_id: UUID
    draft_id: UUID
    media_asset_id: UUID | None = None
    image_request_id: UUID | None = None
    package_json: dict[str, Any] = Field(default_factory=dict)
    approval_status: str
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    revision_requested_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    correlation_id: UUID
    causation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str
    attempt_count: int
    last_error: str | None = None
    occurred_at: datetime | None = None
    available_at: datetime | None = None
    processed_at: datetime | None = None
