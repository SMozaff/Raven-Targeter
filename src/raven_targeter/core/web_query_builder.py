"""Focused web-search query generation for the optional Search API layer."""
from __future__ import annotations

from raven_targeter.config.aliases import get_aliases


def build_web_queries(targets: list[str], keywords: list[str], max_queries: int = 10) -> list[tuple[str, str]]:
    """Return round-robin ``(target, query)`` pairs.

    The web layer is intentionally compact because commercial search APIs
    generally charge per request. Queries emphasize user-created API
    implementations rather than general provider news.
    """
    families: dict[str, list[str]] = {}
    suffix = " ".join(k.strip() for k in keywords if k.strip())
    for target in targets:
        aliases = get_aliases(target)
        name_variants = aliases.names[:2]
        intents = ("API wrapper", "proxy gateway", "unofficial API", "OpenAI compatible")
        queries: list[str] = []
        for name in name_variants:
            for intent in intents:
                q = f'"{name}" "{intent}" GitHub OR API'
                if suffix:
                    q += f" {suffix}"
                queries.append(q)
        families[target] = queries

    out: list[tuple[str, str]] = []
    max_len = max((len(x) for x in families.values()), default=0)
    for idx in range(max_len):
        for target in targets:
            values = families.get(target, [])
            if idx < len(values):
                out.append((target, values[idx]))
                if len(out) >= max_queries:
                    return out
    return out
