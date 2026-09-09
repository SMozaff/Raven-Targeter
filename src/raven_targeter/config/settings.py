"""Application settings, loaded from environment variables and .env.

Never log or display the raw GITHUB_TOKEN value. Use `Settings.has_github_token`
to check presence without exposing the secret.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_TARGETS = ["openai", "anthropic", "gemini", "grok", "deepseek"]


class Settings(BaseSettings):
    """Typed, validated application configuration.

    Values are read from environment variables (prefixed RAVEN_ where noted)
    and/or a `.env` file in the working directory. See `.env.example` for the
    full list of supported variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")

    targets: list[str] = Field(default_factory=lambda: list(DEFAULT_TARGETS))
    lookback_days: int = Field(default=10, ge=1, le=365)
    max_results_per_source: int = Field(default=200, ge=1, le=1000)
    db_url: str = Field(default="sqlite:///data/raven.db")
    log_level: str = Field(default="INFO")

    @field_validator("targets", mode="before")
    @classmethod
    def _split_targets(cls, value: object) -> object:
        """Allow RAVEN_TARGETS to arrive as a comma-separated string."""
        if isinstance(value, str):
            return [t.strip().lower() for t in value.split(",") if t.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @property
    def has_github_token(self) -> bool:
        """True if a (non-empty) GitHub token is configured."""
        return bool(self.github_token and self.github_token.strip())

    def __init__(self, **data: object) -> None:
        # Support both RAVEN_-prefixed and unprefixed env var names for the
        # fields that use the RAVEN_ prefix in the spec, since pydantic-settings
        # only auto-matches on exact field name by default.
        import os

        env_map = {
            "targets": "RAVEN_TARGETS",
            "lookback_days": "RAVEN_LOOKBACK_DAYS",
            "max_results_per_source": "RAVEN_MAX_RESULTS_PER_SOURCE",
            "db_url": "RAVEN_DB_URL",
            "log_level": "RAVEN_LOG_LEVEL",
        }
        for field_name, env_name in env_map.items():
            if field_name not in data and env_name in os.environ:
                data[field_name] = os.environ[env_name]
        super().__init__(**data)


def get_settings() -> Settings:
    """Construct Settings fresh from the current environment/.env file."""
    return Settings()
