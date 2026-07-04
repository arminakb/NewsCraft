from functools import lru_cache
from typing import Optional

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - pydantic-settings is a runtime dependency.
    from pydantic import BaseSettings

    SettingsConfigDict = dict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://newscraft:newscraft@localhost:5432/newscraft"
    github_token: Optional[str] = None
    huggingface_token: Optional[str] = None
    telegram_api_id: Optional[str] = None
    telegram_api_hash: Optional[str] = None
    telegram_session_name: Optional[str] = None
    paper_data_dir: str = "data/papers"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
