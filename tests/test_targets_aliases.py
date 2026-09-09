"""Tests for config/targets.py and config/aliases.py."""

from __future__ import annotations

import pytest

from raven_targeter.config.aliases import (
    TARGET_ALIASES,
    all_intents,
    all_names,
    find_targets_in_text,
    get_aliases,
)
from raven_targeter.config.targets import (
    TARGET_IDS,
    display_name,
    is_known_target,
    normalize_target,
)


def test_default_target_ids():
    assert list(TARGET_IDS) == ["openai", "anthropic", "gemini", "grok", "deepseek"]


def test_normalize_target():
    assert normalize_target("  OpenAI ") == "openai"
    assert normalize_target("ANTHROPIC") == "anthropic"


def test_is_known_target():
    assert is_known_target("openai") is True
    assert is_known_target("Claude") is False  # display names are not IDs
    assert is_known_target("mistral") is False


def test_display_name_known():
    assert display_name("openai") == "OpenAI / ChatGPT"
    assert display_name("GROK") == "xAI / Grok"


def test_display_name_unknown_raises():
    with pytest.raises(ValueError):
        display_name("mistral")


def test_every_target_has_aliases():
    for target in TARGET_IDS:
        aliases = get_aliases(target)
        assert len(aliases.names) >= 2, target
        assert len(aliases.intents) >= 4, target


def test_get_aliases_unknown_raises():
    with pytest.raises(ValueError):
        get_aliases("mistral")


def test_openai_alias_content():
    names = all_names("openai")
    assert "OpenAI" in names
    assert "ChatGPT" in names
    intents = all_intents("openai")
    assert "wrapper" in intents
    assert "proxy" in intents


def test_find_targets_in_text_case_insensitive():
    matched = find_targets_in_text("A new CLAUDE wrapper with FastAPI")
    assert matched == ["anthropic"]


def test_find_targets_in_text_multiple_deterministic_order():
    matched = find_targets_in_text("Gemini and grok and deepseek proxies")
    assert matched == ["gemini", "grok", "deepseek"]


def test_find_targets_in_text_no_match():
    assert find_targets_in_text("a generic REST tutorial") == []


def test_alias_registry_covers_all_targets():
    assert set(TARGET_ALIASES) == set(TARGET_IDS)
