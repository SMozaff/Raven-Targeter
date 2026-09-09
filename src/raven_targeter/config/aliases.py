"""Configurable alias registry for provider targets.

GitHub search must not rely on literal provider names alone (e.g. only
"openai"). Each target maps to a set of *name variants* (what the project
might be called) and *intent keywords* (what kind of project it is: wrapper,
proxy, SDK, ...). The query builder pairs names x intents to generate
focused search queries.

Keep this registry data-driven so new providers or aliases can be added
without touching query-building logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from raven_targeter.config.targets import TARGET_IDS, normalize_target


@dataclass(frozen=True)
class TargetAliases:
    """Name variants and intent keywords for one provider target."""

    names: tuple[str, ...] = field(default_factory=tuple)
    intents: tuple[str, ...] = field(default_factory=tuple)


_GENERIC_INTENTS: tuple[str, ...] = (
    "API",
    "wrapper",
    "proxy",
    "gateway",
    "SDK",
    "client",
    "unofficial API",
    "OpenAI compatible",
)

TARGET_ALIASES: dict[str, TargetAliases] = {
    "openai": TargetAliases(
        names=("OpenAI", "ChatGPT", "GPT", "Responses API"),
        intents=_GENERIC_INTENTS,
    ),
    "anthropic": TargetAliases(
        names=("Anthropic", "Claude", "Claude API"),
        intents=_GENERIC_INTENTS,
    ),
    "gemini": TargetAliases(
        names=("Gemini", "Google AI", "Generative Language API", "Gemini API"),
        intents=_GENERIC_INTENTS,
    ),
    "grok": TargetAliases(
        names=("Grok", "xAI", "xAI API", "Grok API"),
        intents=_GENERIC_INTENTS,
    ),
    "deepseek": TargetAliases(
        names=("DeepSeek", "DeepSeek API"),
        intents=_GENERIC_INTENTS,
    ),
}


def get_aliases(target: str) -> TargetAliases:
    """Return the alias record for a canonical target ID.

    Raises:
        ValueError: If the target is unknown.
    """
    normalized = normalize_target(target)
    if normalized not in TARGET_ALIASES:
        raise ValueError(f"Unknown target: {target!r}")
    return TARGET_ALIASES[normalized]


def all_names(target: str) -> tuple[str, ...]:
    """All searchable name variants for a target."""
    return get_aliases(target).names


def all_intents(target: str) -> tuple[str, ...]:
    """All intent keywords for a target."""
    return get_aliases(target).intents


def find_targets_in_text(text: str) -> list[str]:
    """Return canonical target IDs whose name variants appear in text.

    Matching is case-insensitive substring matching. Targets are returned
    in canonical TARGET_IDS order for determinism.
    """
    lowered = text.lower()
    matched: list[str] = []
    for target in TARGET_IDS:
        names = TARGET_ALIASES[target].names
        if any(name.lower() in lowered for name in names):
            matched.append(target)
    return matched
