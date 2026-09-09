"""Focused GitHub query generation with both creation and activity axes."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from raven_targeter.config.aliases import get_aliases
from raven_targeter.models import QueryVariant, SearchRequest
from raven_targeter.utils.dates import cutoff_utc


def _quote(value: str) -> str:
    return f'"{value.strip().replace(chr(34), "")}"'


def _query_text(name: str, intent: str, keywords: list[str]) -> str:
    suffix = " ".join(_quote(k) for k in keywords if k.strip())
    return f"{_quote(name)} {_quote(intent)} {suffix}".strip()


def build_queries(request: SearchRequest, reference: datetime | None = None) -> list[QueryVariant]:
    """Build round-robin query variants.

    Repository searches cover both `created:` and `pushed:` so old projects
    with fresh activity are discoverable. Issues/PRs cover created + updated.
    Code search has no date qualifier; code hits are later joined to a recent
    parent repository.
    """
    cutoff = cutoff_utc(request.lookback_days, reference).date().isoformat()
    per_target: dict[str, list[QueryVariant]] = defaultdict(list)
    wanted = set(request.sources)

    for target in request.targets:
        aliases = get_aliases(target)
        names = aliases.names[:3]
        intents = aliases.intents[:4]
        if "repository" in wanted:
            for axis in ("created", "pushed"):
                for name in names:
                    for intent in intents:
                        per_target[target].append(QueryVariant(
                            target=target,
                            search_type="repository",
                            query_text=_query_text(name, intent, request.keywords),
                            qualifiers={axis: f">={cutoff}"},
                            freshness_axis=axis,  # type: ignore[arg-type]
                        ))
        if "issue" in wanted:
            for axis in ("created", "updated"):
                for name in names[:2]:
                    for intent in intents[:2]:
                        per_target[target].append(QueryVariant(
                            target=target,
                            search_type="issue",
                            query_text=_query_text(name, intent, request.keywords),
                            qualifiers={axis: f">={cutoff}"},
                            freshness_axis=axis,  # type: ignore[arg-type]
                        ))
        if "pull_request" in wanted:
            for axis in ("created", "updated"):
                for name in names[:2]:
                    per_target[target].append(QueryVariant(
                        target=target,
                        search_type="pull_request",
                        query_text=_query_text(name, intents[0], request.keywords),
                        qualifiers={axis: f">={cutoff}"},
                        freshness_axis=axis,  # type: ignore[arg-type]
                    ))
        if "code" in wanted:
            for name in names[:2]:
                for intent in ("API", "OpenAI compatible"):
                    per_target[target].append(QueryVariant(
                        target=target,
                        search_type="code",
                        query_text=_query_text(name, intent, request.keywords),
                        qualifiers={},
                    ))

    # Round-robin target families, preventing the first provider from
    # consuming the full raw-result budget.
    result: list[QueryVariant] = []
    max_len = max((len(v) for v in per_target.values()), default=0)
    seen: set[tuple[object, ...]] = set()
    for i in range(max_len):
        for target in request.targets:
            seq = per_target.get(target, [])
            if i >= len(seq):
                continue
            q = seq[i]
            if q.dedup_key not in seen:
                seen.add(q.dedup_key)
                result.append(q)
    return result
