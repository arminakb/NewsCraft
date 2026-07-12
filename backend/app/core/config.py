from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NewsCraft Backend"
    database_url: str = Field(default="postgresql+asyncpg://newscraft:newscraft@postgres:5432/newscraft")
    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    media_root: str = "/data/media"
    parser_version: str = "2026-07-03-public-ingestion-v1"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    scheduler_timezone: str = "Asia/Tehran"
    daily_collection_time: str = "06:00"
    scheduler_poll_seconds: float = Field(default=15.0, gt=0)
    worker_poll_seconds: float = Field(default=1.0, gt=0)
    worker_lease_seconds: int = Field(default=120, ge=30)
    worker_heartbeat_seconds: int = Field(default=30, ge=5)

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


settings = Settings()
