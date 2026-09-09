"""Deduplication by canonical URL and repository identity.

The same repository can surface through repository search, code search,
and issue search. Instead of showing it repeatedly, hits that resolve to
the same canonical URL are merged into one discovery with combined
``matched_terms`` and ``evidence``.

Issues/PRs carry their own distinct URLs, so they naturally remain
separate records — but each merged or surviving record keeps its parent
``repo_identity`` (``github.com/owner/repo``) so the GUI can link an
issue/PR back to its repository.
"""

from __future__ import annotations

from raven_targeter.models import Discovery
from raven_targeter.utils.urls import canonical_repo_identity, canonicalize_url


def merge_key(discovery: Discovery) -> str:
    """Grouping key for deduplication: the canonical URL."""
    return discovery.canonical_url or canonicalize_url(discovery.url)


def _merge_union(first: list[str], second: list[str]) -> list[str]:
    """Order-preserving union of two string lists."""
    seen = set(first)
    merged = list(first)
    for item in second:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def merge_group(primary: Discovery, duplicates: list[Discovery]) -> Discovery:
    """Merge a group of same-URL discoveries into one record.

    The primary (first-seen) record keeps its identity fields (id, source,
    provider, title, author, dates, stars). Scores take the per-component
    maximum across the group — merging evidence must never lower a score.
    ``matched_terms`` and ``evidence`` are unioned. A provenance note is
    appended to ``evidence`` recording how many duplicates were merged.
    """
    if not duplicates:
        return primary

    matched = list(primary.matched_terms)
    evidence = list(primary.evidence)
    scores = {
        "relevance_score": primary.relevance_score,
        "freshness_score": primary.freshness_score,
        "implementation_score": primary.implementation_score,
        "engagement_score": primary.engagement_score,
        "confidence_score": primary.confidence_score,
    }
    for dup in duplicates:
        matched = _merge_union(matched, list(dup.matched_terms))
        evidence = _merge_union(evidence, list(dup.evidence))
        for field in scores:
            scores[field] = max(scores[field], float(getattr(dup, field)))

    merged_sources = sorted({d.source_type for d in duplicates} | {primary.source_type})
    evidence = _merge_union(
        evidence,
        [f"Merged {len(duplicates)} duplicate result(s) from: {', '.join(merged_sources)}"],
    )
    data = primary.model_dump()
    data.update(scores)
    data["matched_terms"] = matched
    data["evidence"] = evidence
    return Discovery(**data)


def deduplicate(discoveries: list[Discovery]) -> tuple[list[Discovery], int]:
    """Merge discoveries sharing a canonical URL.

    Returns:
        Tuple of (merged discoveries in first-seen order, duplicates removed).
    """
    groups: dict[str, list[Discovery]] = {}
    order: list[str] = []
    for discovery in discoveries:
        key = merge_key(discovery)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(discovery)

    merged: list[Discovery] = []
    removed = 0
    for key in order:
        group = groups[key]
        merged.append(merge_group(group[0], group[1:]))
        removed += len(group) - 1
    return merged, removed


def attach_repo_identity(discovery: Discovery, owner: str, repo: str) -> Discovery:
    """Return a copy of the discovery with its parent repo identity set."""
    data = discovery.model_dump()
    data["repo_identity"] = canonical_repo_identity(owner, repo)
    return Discovery(**data)
