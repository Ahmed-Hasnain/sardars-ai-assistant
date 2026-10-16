from typing import Literal
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SARDARS_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "Sardars AI Assistant"
    environment: Literal["development", "test", "production"] = "development"

    db_user: str
    db_name: str
    db_password: SecretStr
    db_host: str = "127.0.0.1"
    db_port: int = 5433

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:0.6b"
    ollama_timeout_seconds: float = 120.0
    ollama_keep_alive: int = 0

    qdrant_base_url: str = "http://127.0.0.1:6333"
    brand_definition_profile_url: str | None = "https://sardarandco.com/pages/about-us"
    import_timeout_seconds: float = Field(default=300, gt=0, le=600)
    embedding_batch_size: int = Field(default=2, ge=1, le=8)
    ingestion_storage_dir: Path = Path("data/uploads")
    ingestion_url_hosts: list[str] = ["sardarandco.com"]
