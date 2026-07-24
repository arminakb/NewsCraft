from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator, model_validator

from app.jobs.credential_capabilities import CapabilityStatus
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
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=255)
    bot_token: SecretStr = Field(min_length=1, max_length=4096)
    proxy_profile_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class TelegramDestinationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    target: str | None = Field(default=None, min_length=1, max_length=255)
    proxy_profile_id: UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_nulls_except_route(cls, value):
        if isinstance(value, dict) and any(
            item is None for key, item in value.items() if key != "proxy_profile_id"
        ):
            raise ValueError("destination patch fields cannot be null")
        return value


class TelegramProxyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    proxy_type: Literal["http_connect", "socks5"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65_535)
    username: SecretStr | None = Field(default=None, min_length=1, max_length=1024)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_credentials(self):
        if (self.username is None) != (self.password is None):
            raise ValueError("proxy username and password must be supplied together")
        return self


class TelegramProxyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    proxy_type: Literal["http_connect", "socks5"] | None = None
    host: str | None = Field(default=None, min_length=1, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65_535)

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, value):
        if isinstance(value, dict) and any(item is None for item in value.values()):
            raise ValueError("proxy patch fields cannot be null")
        return value


class TelegramProxyCredentialsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: SecretStr | None = Field(default=None, min_length=1, max_length=1024)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_credentials(self):
        if (self.username is None) != (self.password is None):
            raise ValueError("proxy username and password must be supplied together")
        return self


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
    capability_state: CapabilityStatus


class TelegramDestinationOut(BaseModel):
    id: UUID
    name: str
    target_ref: str
    canonical_target: str
    target_type: Literal["username", "numeric_id", "legacy"]
    enabled: bool
    health_status: str
    configured: bool
    proxy_profile_id: UUID | None
    connection_route: str
    proxy_health_status: str
    telegram_health_status: str
    bot_health_status: str
    target_health_status: str
    administrator_status: str
    failure_code: str | None
    verified_bot_id: int | None
    verified_bot_username: str | None
    verified_chat_id: int | None
    verified_chat_title: str | None
    verified_chat_type: str | None
    last_checked_at: datetime | None
    last_rotated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TelegramProxyOut(BaseModel):
    id: UUID
    name: str
    proxy_type: Literal["http_connect", "socks5"]
    host: str
    port: int
    enabled: bool
    credentials_configured: bool
    reachability_status: str
    failure_code: str | None
    last_checked_at: datetime | None
    last_rotated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TelegramDestinationDependenciesOut(BaseModel):
    automations: int
    publish_jobs: int
    publications: int
    active_jobs: int
    blocked: bool


class TelegramProxyDependenciesOut(BaseModel):
    destinations: int
    blocked: bool


class TelegramCheckOut(BaseModel):
    job_id: UUID
    resource_type: Literal["destination", "proxy"]
    resource_id: UUID
    status: str
    progress: int
    progress_message: str | None
    error_code: str | None
    result: dict
    created_at: datetime
    updated_at: datetime


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


class TelegramProxyAcceptedOut(BaseModel):
    proxy: TelegramProxyOut
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
