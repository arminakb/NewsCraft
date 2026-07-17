from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NewsCraft Backend"
    app_env: str = "development"
    failure_injection_profile: str | None = None
    database_url: str = Field(default="postgresql+asyncpg://newscraft:newscraft@postgres:5432/newscraft")
    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    media_root: str = "/data/media"
    export_root: str = "/data/exports"
    parser_version: str = "2026-07-03-public-ingestion-v1"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    scheduler_timezone: str = "Asia/Tehran"
    daily_collection_time: str = "06:00"
    scheduler_poll_seconds: float = Field(default=15.0, gt=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    worker_lease_seconds: int = Field(default=120, ge=30)
    worker_heartbeat_seconds: int = Field(default=30, ge=5)
    expected_runtime_component_ids: str = "worker-source-generation,worker-publishing,scheduler"
    readiness_required_capabilities: str = ""
    readiness_timeout_seconds: float = Field(default=0.9, gt=0, le=5)
    health_storage_timeout_seconds: float = Field(default=0.25, gt=0, le=2)
    capability_queue_ceiling: int = Field(default=1_000, ge=1)
    capability_retry_after_seconds: int = Field(default=5, ge=1, le=300)
    worker_health_fresh_seconds: int = Field(default=60, ge=5)
    worker_health_unavailable_seconds: int = Field(default=120, ge=10)
    scheduler_health_fresh_seconds: int = Field(default=45, ge=5)
    scheduler_health_unavailable_seconds: int = Field(default=90, ge=10)
    job_stuck_seconds: int = Field(default=900, ge=60)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "openai/gpt-5-mini"
    codex_enabled: bool = False
    codex_executable: str = "codex"
    telegram_media_staging_root: str = "/data/telegram-staging"
    telegram_max_photo_bytes: int = Field(default=10_000_000, gt=0)
    telegram_max_file_bytes: int = Field(default=49_000_000, gt=0)
    telegram_acceptance_fixture_path: str | None = None

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        if self.failure_injection_profile and self.app_env != "test":
            raise SettingsError("failure injection requires APP_ENV=test")
        if self.telegram_acceptance_fixture_path and self.app_env != "test":
            raise SettingsError("Telegram acceptance fixture requires APP_ENV=test")

    @field_validator("scheduler_timezone")
    @classmethod
    def validate_scheduler_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("scheduler_timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("daily_collection_time")
    @classmethod
    def validate_daily_collection_time(cls, value: str) -> str:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise ValueError("daily_collection_time must use HH:MM") from exc
        if parsed.strftime("%H:%M") != value:
            raise ValueError("daily_collection_time must use zero-padded HH:MM")
        return value

    @field_validator("readiness_required_capabilities")
    @classmethod
    def validate_readiness_required_capabilities(cls, value: str) -> str:
        supported = {"generation", "ingestion", "publishing", "scheduling", "source"}
        configured = {part.strip().casefold() for part in value.split(",") if part.strip()}
        if configured - supported:
            raise ValueError("readiness_required_capabilities contains unsupported values")
        return ",".join(sorted(configured))

    @model_validator(mode="after")
    def validate_health_thresholds(self) -> Settings:
        if self.worker_health_unavailable_seconds <= self.worker_health_fresh_seconds:
            raise ValueError("worker unavailable threshold must exceed its fresh threshold")
        if self.scheduler_health_unavailable_seconds <= self.scheduler_health_fresh_seconds:
            raise ValueError("scheduler unavailable threshold must exceed its fresh threshold")
        return self


settings = Settings()
