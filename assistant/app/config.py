from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_owner_id: int = Field(alias="TELEGRAM_OWNER_ID")

    lm_studio_base_url: str = Field(
        default="http://127.0.0.1:1234/v1",
        alias="LM_STUDIO_BASE_URL",
    )
    lm_studio_model: str = Field(
        default="qwen2.5-7b-instruct",
        alias="LM_STUDIO_MODEL",
    )

    assistant_data_dir: Path = Field(alias="ASSISTANT_DATA_DIR")
    timezone: str = Field(default="Europe/Moscow", alias="TIMEZONE")

    @property
    def db_path(self) -> Path:
        return self.assistant_data_dir / "db" / "assistant.sqlite3"

    @property
    def backups_dir(self) -> Path:
        return self.assistant_data_dir / "backups"

    @property
    def inbox_dir(self) -> Path:
        return self.assistant_data_dir / "inbox"


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
