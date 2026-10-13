from typing import Literal

from pydantic import SecretStr
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
