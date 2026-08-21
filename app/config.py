from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Rayda Fleet Copilot"
    environment: str = "development"
    database_url: str = "sqlite:///./data/fleet_copilot.db"
    jwt_secret: str = Field(default="change-me-local-only-secret-32-bytes-min")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    llm_provider: str = "huggingface"
    llm_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    huggingface_api_key: str | None = None
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    acme_admin_password: str = "AcmeAdmin123!"
    globex_admin_password: str = "GlobexAdmin123!"
    initech_admin_password: str = "InitechAdmin123!"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def sqlite_path(self) -> Path | None:
        if not self.database_url.startswith("sqlite:///"):
            return None
        raw_path = self.database_url.replace("sqlite:///", "", 1)
        return Path(raw_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
