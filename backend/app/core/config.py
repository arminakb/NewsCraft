from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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
    article_fetch_timeout_seconds: float = 15.0
    article_fetch_max_bytes: int = 2_000_000
    article_fetch_max_redirects: int = 4
    enrichment_provider: Literal["none", "duckduckgo"] = "none"
    enrichment_timeout_seconds: float = 10.0
    enrichment_max_results: int = 5
    enrichment_max_snippet_chars: int = 500
    llm_provider: Literal["none", "openai", "openrouter"] = "none"
    llm_model: str = "gpt-5-mini"
    llm_request_timeout_seconds: float = 45.0
    llm_max_output_tokens: int = 1800
    llm_base_url: str = "https://api.openai.com/v1"
    openai_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None

    @field_validator("article_fetch_timeout_seconds", "enrichment_timeout_seconds", "llm_request_timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if not 0 < value <= 60:
            raise ValueError("provider timeouts must be greater than 0 and at most 60 seconds")
        return value

    @field_validator("article_fetch_max_bytes")
    @classmethod
    def validate_article_size(cls, value: int) -> int:
        if not 16_384 <= value <= 10_000_000:
            raise ValueError("article_fetch_max_bytes must be between 16384 and 10000000")
        return value

    @field_validator("article_fetch_max_redirects")
    @classmethod
    def validate_redirect_limit(cls, value: int) -> int:
        if not 0 <= value <= 10:
            raise ValueError("article_fetch_max_redirects must be between 0 and 10")
        return value

    @field_validator("enrichment_max_results")
    @classmethod
    def validate_result_limit(cls, value: int) -> int:
        if not 1 <= value <= 10:
            raise ValueError("enrichment_max_results must be between 1 and 10")
        return value

    @field_validator("enrichment_max_snippet_chars")
    @classmethod
    def validate_snippet_limit(cls, value: int) -> int:
        if not 80 <= value <= 1000:
            raise ValueError("enrichment_max_snippet_chars must be between 80 and 1000")
        return value

    @field_validator("llm_max_output_tokens")
    @classmethod
    def validate_llm_output_limit(cls, value: int) -> int:
        if not 256 <= value <= 8000:
            raise ValueError("llm_max_output_tokens must be between 256 and 8000")
        return value

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LLM_BASE_URL must be an absolute HTTP(S) URL without credentials, query, or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_llm_configuration(self):
        if self.llm_provider == "openai" and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "openrouter":
            if self.openrouter_api_key is None:
                raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")
            parsed = urlsplit(self.llm_base_url)
            if parsed.scheme != "https" or parsed.hostname != "openrouter.ai":
                raise ValueError("LLM_BASE_URL must resolve to https://openrouter.ai when LLM_PROVIDER=openrouter")
        return self


settings = Settings()
