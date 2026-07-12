from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.jobs.schemas import JobAcceptedOut

SecretRef = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")]


class TelegramSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel_ref: str = Field(min_length=1, max_length=255)
    access_mode: Literal["public_html", "mtproto_user"] = "public_html"
    api_id_secret_ref: SecretRef | None = None
    api_hash_secret_ref: SecretRef | None = None
    session_secret_ref: SecretRef | None = None
    language_hint: str = Field(default="fa", min_length=2, max_length=12)

    @model_validator(mode="after")
    def validate_secret_mode(self):
        refs = (self.api_id_secret_ref, self.api_hash_secret_ref, self.session_secret_ref)
        if self.access_mode == "public_html" and any(refs):
            raise ValueError("public_html cannot store MTProto credential references")
        if self.access_mode == "mtproto_user" and not all(refs):
            raise ValueError(
                "mtproto_user requires api_id_secret_ref, api_hash_secret_ref, and session_secret_ref"
            )
        return self


class TelegramDestinationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_ref: str = Field(min_length=1, max_length=255)
    secret_ref: SecretRef
    allow_auto_publish: bool = False


class TelegramContentFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1, max_length=200)
    include_terms: list[str] = Field(default_factory=list, max_length=20)
    exclude_terms: list[str] = Field(default_factory=list, max_length=20)
    min_text_characters: int = Field(default=1, ge=0, le=100_000)
    require_media: bool = False
    research_provider_profile_id: UUID | None = None


class TelegramQuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = "Asia/Tehran"
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def validate_non_empty_window(self):
        if self.start == self.end:
            raise ValueError("quiet-hours start and end cannot be identical")
        return self


class TelegramRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: int = Field(default=30, ge=1, le=3600)
    max_delay_seconds: int = Field(default=1800, ge=1, le=86400)

    @model_validator(mode="after")
    def validate_delay_order(self):
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be greater than or equal to base_delay_seconds")
        return self


class TelegramRouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_id: UUID
    destination_id: UUID
    brand_profile_id: UUID
    prompt_template_version_id: UUID
    ai_provider_profile_id: UUID
    access_mode: Literal["public_html", "mtproto_user"]
    research_mode: Literal["off", "manual", "auto_if_incomplete"] = "off"
    content_filters: TelegramContentFilters = Field(default_factory=TelegramContentFilters)
    media_policy: Literal["preserve", "omit", "replace_manually"] = "preserve"
    attribution_policy: Literal["preserve", "remove", "custom"] = "preserve"
    custom_footer: str | None = Field(default=None, max_length=512)
    publishing_policy: Literal["review_required", "auto_publish"] = "review_required"
    poll_interval_seconds: int = Field(default=300, ge=60, le=86400)
    quiet_hours: TelegramQuietHours | None = None
    retry_policy: TelegramRetryPolicy = Field(default_factory=TelegramRetryPolicy)
    confirm_auto_publish: bool = False

    @model_validator(mode="after")
    def validate_auto_and_attribution(self):
        if self.publishing_policy == "auto_publish" and not self.confirm_auto_publish:
            raise ValueError("auto_publish requires confirm_auto_publish=true")
        if self.attribution_policy == "custom" and not (self.custom_footer or "").strip():
            raise ValueError("custom attribution requires custom_footer")
        if self.research_mode == "off" and self.content_filters.research_provider_profile_id is not None:
            raise ValueError("off research mode cannot select a research provider profile")
        if self.research_mode != "off" and self.content_filters.research_provider_profile_id is None:
            raise ValueError("manual and automatic research require a research provider profile")
        return self


class TelegramResearchPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_mode: Literal["off", "manual", "auto_if_incomplete"]
    research_provider_profile_id: UUID | None = None

    @model_validator(mode="after")
    def validate_profile_selection(self):
        if self.research_mode == "off" and self.research_provider_profile_id is not None:
            raise ValueError("off research mode requires a null research provider profile")
        if self.research_mode != "off" and self.research_provider_profile_id is None:
            raise ValueError("manual and automatic research require a research provider profile")
        return self


class TelegramRouteBackfillIn(BaseModel):
    count: int | None = Field(default=None, ge=1, le=100)
    since: datetime | None = None

    @model_validator(mode="after")
    def validate_bound(self):
        if (self.count is None) == (self.since is None):
            raise ValueError("provide exactly one of count or since")
        if self.since is not None:
            if self.since.tzinfo is None or self.since.utcoffset() is None:
                raise ValueError("since must include a timezone offset")
            if self.since < datetime.now(UTC) - timedelta(days=30):
                raise ValueError("since cannot be older than 30 days")
        return self


class TelegramRouteDryRunIn(BaseModel):
    source_message_id: int | None = Field(default=None, ge=1)


class TelegramSourceOut(BaseModel):
    id: UUID
    name: str
    channel_ref: str
    access_mode: str
    language_hint: str | None
    configured: bool


class TelegramDestinationOut(BaseModel):
    id: UUID
    name: str
    target_ref: str
    enabled: bool
    health_status: str
    configured: bool
    settings: dict


class TelegramRouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    source_id: UUID
    destination_id: UUID
    brand_profile_id: UUID
    prompt_template_version_id: UUID
    ai_provider_profile_id: UUID
    access_mode: str
    research_mode: str
    content_filters: dict
    media_policy: str
    attribution_policy: str
    custom_footer: str | None
    publishing_policy: str
    poll_interval_seconds: int
    quiet_hours: dict
    retry_policy: dict
    cursor_state: dict
    enabled: bool
    paused_at: datetime | None
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TelegramDestinationAcceptedOut(BaseModel):
    destination: TelegramDestinationOut
    job: JobAcceptedOut


class TelegramRouteAcceptedOut(BaseModel):
    route: TelegramRouteOut
    job: JobAcceptedOut


class TelegramAutomationOptionsOut(BaseModel):
    sources: list[dict]
    destinations: list[dict]
    brand_profiles: list[dict]
    prompt_template_versions: list[dict]
    ai_provider_profiles: list[dict]
