"""Query builder: focused GitHub search queries from targets x aliases.

Instead of one giant query, the builder generates multiple focused
``name x intent`` variants (e.g. ``"Claude" wrapper``, ``"Anthropic" proxy``)
per target and search type. Variants are deduplicated so overlapping
aliases never explode into hundreds of redundant queries.

Date qualifiers are attached as structured data (not string-concatenated
URLs): repository/issue/PR variants carry a ``created`` qualifier derived
from the lookback window. Code search variants carry **no** date
qualifiers — GitHub's code search API does not support them; code is
inspected within repositories shortlisted by the other searches.
"""

from __future__ import annotations

from datetime import datetime

from raven_targeter.config.aliases import get_aliases
from raven_targeter.models import QueryVariant, SearchRequest
from raven_targeter.utils.dates import cutoff_utc

# Caps keep the query count bounded: 12 repo + 4 issue + 2 PR + 4 code = 22
# per target at most, ~110 for the five default targets before dedup.
_MAX_REPO_NAMES = 3
_MAX_REPO_INTENTS = 4
_MAX_ISSUE_NAMES = 2
_MAX_ISSUE_INTENTS = 2
_MAX_PR_NAMES = 2
_MAX_PR_INTENTS = 1
_MAX_CODE_NAMES = 2
_MAX_CODE_INTENTS = 2

_SOURCE_TO_SEARCH_TYPE = {
    "repository": "repository",
    "code": "code",
    "issue": "issue",
    "pull_request": "pull_request",
}


def _quote(phrase: str) -> str:
    """Wrap a search phrase in double quotes for exact-phrase matching."""
    cleaned = phrase.strip().replace('"', "")
    return f'"{cleaned}"'


def _with_keywords(query_text: str, keywords: list[str]) -> str:
    """Append user keywords to a query's keyword portion."""
    parts = [query_text] + [_quote(k) for k in keywords if k.strip()]
    return " ".join(parts)


def _created_qualifier(lookback_days: int, reference: datetime | None) -> dict[str, str]:
    """A ``created`` date qualifier for the lookback window (YYYY-MM-DD)."""
    cutoff = cutoff_utc(lookback_days, reference=reference)
    return {"created": f">={cutoff.date().isoformat()}"}


def build_queries(
    request: SearchRequest, reference: datetime | None = None
) -> list[QueryVariant]:
    """Generate deduplicated query variants for a search request.

    Args:
        request: Validated search parameters (targets, keywords, window).
        reference: Optional reference "now" (UTC-aware) for testing.

    Returns:
        Deduplicated variants in deterministic order: targets in request
        order, then repository, issue, pull-request, and code queries.
    """
    variants: list[QueryVariant] = []
    wanted = {
        _SOURCE_TO_SEARCH_TYPE[s]
        for s in request.sources
        if s in _SOURCE_TO_SEARCH_TYPE
    }

    for target in request.targets:
        aliases = get_aliases(target)
        names = aliases.names
        intents = aliases.intents

        if "repository" in wanted:
            qualifier = _created_qualifier(request.lookback_days, reference)
            for name in names[:_MAX_REPO_NAMES]:
                for intent in intents[:_MAX_REPO_INTENTS]:
                    text = _with_keywords(
                        f"{_quote(name)} {_quote(intent)}", request.keywords
                    )
                    variants.append(
                        QueryVariant(
                            target=target,
                            search_type="repository",
                            query_text=text,
                            qualifiers=dict(qualifier),
                        )
                    )

        if "issue" in wanted:
            qualifier = _created_qualifier(request.lookback_days, reference)
            for name in names[:_MAX_ISSUE_NAMES]:
                for intent in intents[:_MAX_ISSUE_INTENTS]:
                    text = _with_keywords(
                        f"{_quote(name)} {_quote(intent)}", request.keywords
                    )
                    variants.append(
                        QueryVariant(
                            target=target,
                            search_type="issue",
                            query_text=text,
                            qualifiers=dict(qualifier),
                        )
                    )

        if "pull_request" in wanted:
            qualifier = _created_qualifier(request.lookback_days, reference)
            for name in names[:_MAX_PR_NAMES]:
                for intent in intents[:_MAX_PR_INTENTS]:
                    text = _with_keywords(
                        f"{_quote(name)} {_quote(intent)}", request.keywords
                    )
                    variants.append(
                        QueryVariant(
                            target=target,
                            search_type="pull_request",
                            query_text=text,
                            qualifiers=dict(qualifier),
                        )
                    )

        if "code" in wanted:
            # No date qualifiers: unsupported by GitHub code search.
            for name in names[:_MAX_CODE_NAMES]:
                for intent in intents[:_MAX_CODE_INTENTS]:
                    text = _with_keywords(
                        f"{_quote(name)} {_quote(intent)}", request.keywords
                    )
                    variants.append(
                        QueryVariant(
                            target=target,
                            search_type="code",
                            query_text=text,
                            qualifiers={},
                        )
                    )

    # Deduplicate while preserving first-seen order.
    seen: set[tuple[str, str, str]] = set()
    deduped: list[QueryVariant] = []
    for variant in variants:
        if variant.dedup_key not in seen:
            seen.add(variant.dedup_key)
            deduped.append(variant)
    return deduped
