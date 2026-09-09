"""Deduplication that merges repository and code evidence by repository identity."""
from __future__ import annotations

from raven_targeter.models import CandidateEndpoint, Discovery
from raven_targeter.utils.urls import canonicalize_url


def merge_key(d: Discovery) -> str:
    if d.source_type in {"repository", "code"} and d.repo_identity:
        return f"repo:{d.repo_identity.lower()}"
    return f"url:{canonicalize_url(d.canonical_url or d.url)}"


def _union(a: list[str], b: list[str]) -> list[str]:
    return list(dict.fromkeys([*a, *b]))


def _merge_endpoints(a: list[CandidateEndpoint], b: list[CandidateEndpoint]) -> list[CandidateEndpoint]:
    by_url = {x.url: x for x in a}
    for item in b:
        old = by_url.get(item.url)
        if old is None or item.confidence > old.confidence:
            by_url[item.url] = item
    return sorted(by_url.values(), key=lambda x: (-x.confidence, x.url))


def merge_group(group: list[Discovery]) -> Discovery:
    # Prefer repository metadata over code metadata as primary.
    primary = next((d for d in group if d.source_type == "repository"), group[0])
    updates = primary.model_dump()
    for d in group:
        if d.id == primary.id:
            continue
        updates["matched_terms"] = _union(updates["matched_terms"], d.matched_terms)
        updates["evidence"] = _union(updates["evidence"], d.evidence)
        updates["candidate_endpoints"] = [x.model_dump() for x in _merge_endpoints(
            [CandidateEndpoint(**x) if isinstance(x, dict) else x for x in updates["candidate_endpoints"]],
            d.candidate_endpoints,
        )]
        for field in ("relevance_score", "freshness_score", "implementation_score", "engagement_score", "confidence_score"):
            updates[field] = max(float(updates[field]), float(getattr(d, field)))
        if primary.description is None and d.description:
            updates["description"] = d.description
    if len(group) > 1:
        updates["evidence"] = _union(updates["evidence"], [f"Merged {len(group)-1} related hit(s) by repository identity"])
    return Discovery(**updates)


def deduplicate(discoveries: list[Discovery]) -> tuple[list[Discovery], int]:
    groups: dict[str, list[Discovery]] = {}
    order: list[str] = []
    for d in discoveries:
        key = merge_key(d)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)
    merged = [merge_group(groups[k]) for k in order]
    return merged, len(discoveries) - len(merged)
