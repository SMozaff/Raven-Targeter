"""Search aliases for each provider target."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetAliases:
    names: tuple[str, ...]
    intents: tuple[str, ...]


GENERIC_INTENTS = (
    "API", "wrapper", "proxy", "gateway", "SDK", "client",
    "unofficial API", "OpenAI compatible",
)

TARGET_ALIASES: dict[str, TargetAliases] = {
    "openai": TargetAliases(("OpenAI", "ChatGPT", "GPT", "Responses API"), GENERIC_INTENTS),
    "anthropic": TargetAliases(("Anthropic", "Claude", "Claude API"), GENERIC_INTENTS),
    "gemini": TargetAliases(("Gemini", "Google AI", "Generative Language API"), GENERIC_INTENTS),
    "grok": TargetAliases(("Grok", "xAI", "xAI API"), GENERIC_INTENTS),
    "deepseek": TargetAliases(("DeepSeek", "DeepSeek API"), GENERIC_INTENTS),
}


def get_aliases(target: str) -> TargetAliases:
    key = target.strip().lower()
    if key not in TARGET_ALIASES:
        raise ValueError(f"Unknown target: {target!r}")
    return TARGET_ALIASES[key]
