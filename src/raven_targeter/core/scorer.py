"""Deterministic classification and scoring."""
from __future__ import annotations

import math

from raven_targeter.models import Discovery
from raven_targeter.utils.dates import cutoff_utc, now_utc


def classify(text: str, source_type: str) -> str:
    low = text.lower()
    rules = [
        ("openai-compatible", ("openai compatible", "openai-compatible")),
        ("proxy", ("proxy", "reverse proxy")),
        ("gateway", ("gateway",)),
        ("sdk", (" sdk", "software development kit")),
        ("api-wrapper", ("wrapper", "api wrapper")),
        ("client", ("client",)),
        ("automation", ("automation", "workflow")),
        ("example", ("example", "demo")),
    ]
    for label, markers in rules:
        if any(m in low for m in markers):
            return label
    if source_type in {"issue", "pull_request"}:
        return "discussion"
    return "unknown"


def score(d: Discovery, lookback_days: int) -> Discovery:
    text = "\n".join([d.title, d.description or "", *d.evidence]).lower()
    rel = min(100.0, 25 + 12 * len(d.matched_terms) + (20 if "api" in text else 0))
    impl = min(100.0, 15 + 22 * len(d.candidate_endpoints) + (20 if d.source_type == "code" else 0))
    cutoff = cutoff_utc(lookback_days)
    dates = [x for x in (d.created_at, d.pushed_at, d.updated_at) if x]
    fresh = 100.0 if any(x >= cutoff for x in dates) else 0.0
    if d.source_type == "web" and any("Server-side recency filter" in e for e in d.evidence):
        fresh = max(fresh, 80.0)
    eng = min(100.0, math.log10(1 + (d.stars or 0) + (d.forks or 0) * 2) * 30)
    conf = min(100.0, 40 + 15 * len(d.evidence) + 20 * len(d.candidate_endpoints))
    classification = classify(text, d.source_type)
    return d.model_copy(update={
        "relevance_score": rel,
        "implementation_score": impl,
        "freshness_score": fresh,
        "engagement_score": eng,
        "confidence_score": conf,
        "classification": classification,
        "discovered_at": d.discovered_at or now_utc(),
    })
