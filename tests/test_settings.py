"""Tests for config/settings.py."""

from __future__ import annotations

from raven_targeter.config.settings import DEFAULT_TARGETS, Settings


def test_defaults_with_no_env(monkeypatch):
    for var in [
        "GITHUB_TOKEN",
        "RAVEN_TARGETS",
        "RAVEN_LOOKBACK_DAYS",
        "RAVEN_MAX_RESULTS_PER_SOURCE",
        "RAVEN_DB_URL",
        "RAVEN_LOG_LEVEL",
    ]:
        monkeypatch.delenv(var, raising=False)

    s = Settings(_env_file=None)

    assert s.targets == DEFAULT_TARGETS
    assert s.lookback_days == 10
    assert s.max_results_per_source == 200
    assert s.db_url == "sqlite:///data/raven.db"
    assert s.log_level == "INFO"
    assert s.github_token is None
    assert s.has_github_token is False


def test_missing_github_token_warning_condition(monkeypatch):
    """has_github_token must be False for None, empty string, and whitespace."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert Settings(_env_file=None).has_github_token is False
    assert Settings(_env_file=None, github_token="").has_github_token is False
    assert Settings(_env_file=None, github_token="   ").has_github_token is False
    assert Settings(_env_file=None, github_token="ghp_abc123").has_github_token is True


def test_targets_from_comma_separated_env(monkeypatch):
    monkeypatch.setenv("RAVEN_TARGETS", "openai, Anthropic ,gemini")
    s = Settings(_env_file=None)
    assert s.targets == ["openai", "anthropic", "gemini"]


def test_lookback_days_from_env(monkeypatch):
    monkeypatch.setenv("RAVEN_LOOKBACK_DAYS", "3")
    s = Settings(_env_file=None)
    assert s.lookback_days == 3


def test_lookback_days_bounds():
    s = Settings(_env_file=None, lookback_days=1)
    assert s.lookback_days == 1
    s2 = Settings(_env_file=None, lookback_days=365)
    assert s2.lookback_days == 365


def test_log_level_normalized_uppercase(monkeypatch):
    monkeypatch.setenv("RAVEN_LOG_LEVEL", "debug")
    s = Settings(_env_file=None)
    assert s.log_level == "DEBUG"


def test_db_url_from_env(monkeypatch):
    monkeypatch.setenv("RAVEN_DB_URL", "sqlite:///custom.db")
    s = Settings(_env_file=None)
    assert s.db_url == "sqlite:///custom.db"
