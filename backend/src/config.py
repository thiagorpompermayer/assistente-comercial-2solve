"""Configuração central — segredos só por variável de ambiente (regra dura 4)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Assistente Comercial 2Solve"
    api_version: str = "v1"

    database_url: str = "sqlite:///./assistente.db"

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    claude_model_proposal: str = "claude-opus-4-8"

    omie_app_key: str = ""
    omie_app_secret: str = ""
    omie_base_url: str = "https://app.omie.com.br/api/v1"

    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_mailbox: str = ""

    scheduler_enabled: bool = False
    monitor_cron_hour: int = 6
    email_triage_cron_hour: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
