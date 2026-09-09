"""Application settings.

Non-secret settings may come from environment variables or the desktop GUI.
Secrets are resolved separately from the OS keychain. Environment variables
for secrets remain supported for CI/headless use but are never written by the
application.
"""
from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TARGETS = ["openai", "anthropic", "gemini", "grok", "deepseek"]
SEARCH_PROVIDERS = ("disabled", "serpapi")
SEARCH_ENGINES = ("google", "baidu", "bing", "yandex")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Advanced/headless overrides. Desktop users should use Settings -> APIs.
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    search_api_key: str | None = Field(default=None, alias="SEARCH_API_KEY")

    targets: list[str] = Field(default_factory=lambda: list(DEFAULT_TARGETS), alias="RAVEN_TARGETS")
    lookback_days: int = Field(default=10, ge=1, le=365, alias="RAVEN_LOOKBACK_DAYS")
    max_results_per_source: int = Field(default=200, ge=1, le=2000, alias="RAVEN_MAX_RESULTS_PER_SOURCE")
    db_url: str = Field(default="sqlite:///data/raven.db", alias="RAVEN_DB_URL")
    log_level: str = Field(default="INFO", alias="RAVEN_LOG_LEVEL")

    search_api_provider: str = Field(default="disabled", alias="RAVEN_SEARCH_API_PROVIDER")
    search_api_engine: str = Field(default="google", alias="RAVEN_SEARCH_API_ENGINE")
    search_api_base_url: str = Field(
        default="https://serpapi.com/search.json", alias="RAVEN_SEARCH_API_BASE_URL"
    )
    search_api_max_queries: int = Field(default=10, ge=1, le=100, alias="RAVEN_SEARCH_API_MAX_QUERIES")

    @field_validator("targets", mode="before")
    @classmethod
    def split_targets(cls, value: object) -> object:
        if isinstance(value, str):
            return [x.strip().lower() for x in value.split(",") if x.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("search_api_provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized if normalized in SEARCH_PROVIDERS else "disabled"
        return value

    @field_validator("search_api_engine", mode="before")
    @classmethod
    def normalize_engine(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized if normalized in SEARCH_ENGINES else "google"
        return value

    @property
    def has_github_token(self) -> bool:
        return bool(self.github_token and self.github_token.strip())

    @property
    def has_search_api_key(self) -> bool:
        return bool(self.search_api_key and self.search_api_key.strip())


def get_settings() -> Settings:
    return Settings()
