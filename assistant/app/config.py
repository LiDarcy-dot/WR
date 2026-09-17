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
    telegram_group_id: int | None = Field(default=None, alias="TELEGRAM_GROUP_ID")
    # Optional MTProto credentials to list forum topics (defaults = Telegram Android)
    telegram_api_id: int | None = Field(default=None, alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(default="", alias="TELEGRAM_API_HASH")

    lm_studio_base_url: str = Field(
        default="http://127.0.0.1:1234/v1",
        alias="LM_STUDIO_BASE_URL",
    )
    lm_studio_model: str = Field(
        default="qwen/qwen3.5-9b",
        alias="LM_STUDIO_MODEL",
    )
    lm_studio_vision_model: str = Field(
        default="",
        alias="LM_STUDIO_VISION_MODEL",
    )
    lm_studio_transcribe_model: str = Field(
        default="",
        alias="LM_STUDIO_TRANSCRIBE_MODEL",
    )

    assistant_data_dir: Path = Field(alias="ASSISTANT_DATA_DIR")
    timezone: str = Field(default="Europe/Moscow", alias="TIMEZONE")
    web_port: int = Field(default=8765, alias="WEB_PORT")

    auto_update: bool = Field(default=True, alias="AUTO_UPDATE")
    auto_update_interval_sec: int = Field(default=120, alias="AUTO_UPDATE_INTERVAL_SEC")
    auto_update_repo: str = Field(default="LiDarcy-dot/WR", alias="AUTO_UPDATE_REPO")
    auto_update_branch: str = Field(
        default="cursor/local-assistant-scaffold-d6ce",
        alias="AUTO_UPDATE_BRANCH",
    )

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
