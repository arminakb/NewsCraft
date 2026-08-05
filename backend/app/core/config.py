from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError

_SECRET_SETTINGS_DIR = "/run/secrets" if Path("/run/secrets").is_dir() else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir=_SECRET_SETTINGS_DIR,
        extra="ignore",
    )

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
    capability_observation_ttl_seconds: int = Field(default=120, ge=30, le=3600)
    worker_health_fresh_seconds: int = Field(default=60, ge=5)
    worker_health_unavailable_seconds: int = Field(default=120, ge=10)
    scheduler_health_fresh_seconds: int = Field(default=45, ge=5)
    scheduler_health_unavailable_seconds: int = Field(default=90, ge=10)
    job_stuck_seconds: int = Field(default=900, ge=60)
    restart_warning_window_seconds: int = Field(default=600, ge=60, le=86_400)
    restart_warning_count: int = Field(default=3, ge=2, le=32)
    recovery_observation_window_seconds: int = Field(default=86_400, ge=60, le=604_800)
    recovery_warning_count: int = Field(default=2, ge=2, le=100)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_default_model: str = "openai/gpt-5-mini"
    generation_invalid_output_quarantine_enabled: bool = False
    generation_invalid_output_quarantine_root: str = "/data/generation-invalid-output"
    generation_invalid_output_quarantine_recipient_file: str = "/run/secrets/GENERATION_QUARANTINE_AGE_RECIPIENT"
    generation_invalid_output_quarantine_max_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)
    generation_invalid_output_quarantine_ttl_days: int = Field(default=7, ge=1, le=7)
    generation_invalid_output_quarantine_age_executable: str = "age"
    codex_enabled: bool = False
    codex_executable: str = "codex"
    telegram_media_staging_root: str = "/data/telegram-staging"
    telegram_max_photo_bytes: int = Field(default=10_000_000, gt=0)
    telegram_max_file_bytes: int = Field(default=49_000_000, gt=0)
    telegram_proxy_allowed_ports: str = "80,443,1080,3128,8080,8443"
    telegram_proxy_connect_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    telegram_api_read_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    telegram_acceptance_fixture_path: str | None = None
    worker_secret_root: str = "/run/secrets"
    application_auth_mode: Literal["local_owner", "profile"] = "local_owner"
    security_codex_token: SecretStr | None = None
    security_codex_scopes: str = (
        "settings:read,providers:read,destinations:read,prompts:read,automations:read,jobs:read"
    )
    security_internal_token: SecretStr | None = None
    security_internal_scopes: str = "jobs:read,jobs:write,providers:read,destinations:read"
    security_audit_enabled: bool = True
    codex_gateway_hash_key: SecretStr | None = None
    codex_gateway_public_url: str = "http://localhost:8000"
    codex_gateway_pairing_ttl_seconds: int = Field(default=300, ge=60, le=900)
    codex_gateway_credential_ttl_seconds: int = Field(default=2_592_000, ge=300, le=31_536_000)
    codex_gateway_heartbeat_interval_seconds: int = Field(default=30, ge=5, le=300)
    codex_gateway_heartbeat_fresh_seconds: int = Field(default=90, ge=10, le=3600)
    codex_gateway_heartbeat_stale_seconds: int = Field(default=300, ge=30, le=86_400)
    codex_gateway_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    codex_gateway_pairing_create_limit: int = Field(default=10, ge=1, le=1000)
    codex_gateway_pair_exchange_limit: int = Field(default=20, ge=1, le=1000)
    codex_gateway_heartbeat_limit: int = Field(default=120, ge=1, le=10_000)
    codex_gateway_capability_limit: int = Field(default=120, ge=1, le=10_000)
    secret_key_version: str = "v1"
    secret_master_key: SecretStr | None = None
    secret_previous_keys: SecretStr | None = None

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
        if self.codex_gateway_heartbeat_stale_seconds <= self.codex_gateway_heartbeat_fresh_seconds:
            raise ValueError("Codex stale heartbeat threshold must exceed fresh threshold")
        gateway_url = urlsplit(self.codex_gateway_public_url)
        if (
            gateway_url.scheme not in {"http", "https"}
            or not gateway_url.hostname
            or gateway_url.username is not None
            or gateway_url.password is not None
            or gateway_url.query
            or gateway_url.fragment
        ):
            raise ValueError("Codex Gateway public URL must be a safe HTTP(S) base URL")
        if (
            self.app_env == "production"
            and gateway_url.scheme != "https"
            and gateway_url.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("production Codex Gateway public URL must use HTTPS")
        if self.application_auth_mode == "local_owner":
            configured_origins = [value.strip() for value in self.cors_origins.split(",") if value.strip()]
            if not configured_origins or not all(_is_loopback_http_origin(value) for value in configured_origins):
                raise ValueError("local_owner mode requires loopback-only CORS origins")
        return self

    @field_validator("security_codex_scopes", "security_internal_scopes")
    @classmethod
    def validate_security_scopes(cls, value: str) -> str:
        from app.security.scopes import ALL_SCOPES

        configured = {part.strip().casefold() for part in value.split(",") if part.strip()}
        if configured - ALL_SCOPES:
            raise ValueError("security scopes contain unsupported values")
        return ",".join(sorted(configured))

    @field_validator("secret_key_version")
    @classmethod
    def validate_secret_key_version(cls, value: str) -> str:
        if not value or len(value) > 32 or not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError("secret_key_version must be a short identifier")
        return value


def _is_loopback_http_origin(value: str) -> bool:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return False
    try:
        parsed_port = parsed.port
    except ValueError:
        return False
    del parsed_port
    if parsed.hostname.casefold().rstrip(".") == "localhost":
        return True
    try:
        return ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


settings = Settings()
