from pydantic import Field
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


settings = Settings()
