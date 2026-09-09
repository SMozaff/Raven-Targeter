"""Canonical AI provider target identifiers.

Target IDs are lowercase, stable strings used across settings, query
building, scoring, and persistence. Display names are for the GUI only —
never use them as identity keys.
"""

from __future__ import annotations

TARGET_IDS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "gemini",
    "grok",
    "deepseek",
)

TARGET_DISPLAY_NAMES: dict[str, str] = {
    "openai": "OpenAI / ChatGPT",
    "anthropic": "Anthropic / Claude",
    "gemini": "Google Gemini",
    "grok": "xAI / Grok",
    "deepseek": "DeepSeek",
}


def normalize_target(value: str) -> str:
    """Normalize a user-supplied target string to its canonical ID."""
    return value.strip().lower()


def is_known_target(value: str) -> bool:
    """True if the value is a known canonical target ID."""
    return normalize_target(value) in TARGET_IDS


def display_name(target: str) -> str:
    """Human-readable display name for a canonical target ID."""
    normalized = normalize_target(target)
    if normalized not in TARGET_DISPLAY_NAMES:
        raise ValueError(f"Unknown target: {target!r}")
    return TARGET_DISPLAY_NAMES[normalized]
