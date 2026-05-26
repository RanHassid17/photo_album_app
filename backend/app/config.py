from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: str = "sk-ant-REPLACE_ME"
    anthropic_model: str = "claude-sonnet-4-6"

    database_url: str = "postgresql+psycopg://album:album@localhost:5432/album"
    redis_url: str = "redis://localhost:6379/0"

    photo_storage_dir: Path = Path("./photo_storage")
    export_dir: Path = Path("./exports")

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.photo_storage_dir.mkdir(parents=True, exist_ok=True)
    s.export_dir.mkdir(parents=True, exist_ok=True)
    return s
