from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    app_timezone: str = "Asia/Yekaterinburg"
    class_name: str = "7Л1"
    database_url: str = "sqlite+aiosqlite:///./school_payments.db"
    receipts_root: Path = Path("storage/receipts")
    reminder_days: Annotated[list[int], NoDecode] = [1, 5, 10]
    scheduler_enabled: bool = True
    max_delivery_mode: str = "polling"
    seed_on_start: bool = True
    log_level: str = "INFO"

    max_token: str = ""
    max_bot_id: int = 437985824
    max_bot_name: str = "Оплата 7Л1"
    max_bot_username: str = "id183210316680_bot"
    max_admin_ids: Annotated[set[int], NoDecode] = set()
    max_api_base_url: str = "https://platform-api2.max.ru"
    max_webhook_url: str = ""
    max_webhook_secret: str = ""
    max_ca_bundle: Path | None = None

    server_ssh_user: str = ""
    server_ssh_host: str = Field(
        default="", validation_alias=AliasChoices("SERVER_SSH_HOST", "SERVER__SSH_HOST")
    )
    server_ssh_password: str = ""
    deploy_path: str = "/opt/max-school-payments-bot"

    google_sheets_credentials_file: str = ""
    google_sheets_document_id: str = ""

    @field_validator("reminder_days", mode="before")
    @classmethod
    def parse_days(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        return value

    @field_validator("max_bot_id", mode="before")
    @classmethod
    def parse_bot_id(cls, value: object) -> object:
        return 437985824 if value in (None, "") else value

    @field_validator("max_delivery_mode")
    @classmethod
    def validate_delivery_mode(cls, value: str) -> str:
        value = value.lower()
        if value not in {"polling", "webhook"}:
            raise ValueError("MAX_DELIVERY_MODE must be polling or webhook")
        return value

    @field_validator("max_admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return {int(part.strip()) for part in value.split(",") if part.strip()}
        return value

    @property
    def max_verify(self) -> bool | str:
        return str(self.max_ca_bundle) if self.max_ca_bundle else True


@lru_cache
def get_settings() -> Settings:
    return Settings()
