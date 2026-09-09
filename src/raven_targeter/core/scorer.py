"""Transparent, deterministic scoring for discoveries.

Starting weights (V1):

- 35% relevance — how well the result matches target aliases/intents
- 30% freshness — how recently it was created or pushed
- 15% implementation evidence — presence of real API code patterns
- 10% GitHub engagement — stars/forks (log-scaled)
- 10% uniqueness/confidence — matched terms, evidence depth, date quality

All weights live in :data:`SCORING_WEIGHTS`. Change them here (and only
here), document the change, and update ``tests/test_scorer.py`` — per
AGENTS.md the weights must stay centralized.

A repository with actual API implementation code always ranks above one
that merely mentions a provider name: implementation evidence and
classification feed both the relevance and implementation components.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raven_targeter.models import CLASSIFICATIONS, Classification
from raven_targeter.utils.dates import cutoff_utc, ensure_utc, now_utc

# Centralized scoring weights. Keys are component names, values are fractions
# that must sum to 1.0 (enforced by test_scorer.py::test_weights_sum_to_one).
SCORING_WEIGHTS: dict[str, float] = {
    "relevance": 0.35,
    "freshness": 0.30,
    "implementation_evidence": 0.15,
    "engagement": 0.10,
    "uniqueness_confidence": 0.10,
}

_RELEVANCE_PER_TERM = 20.0
_RELEVANCE_CLASSIFICATION_BONUS = 15.0
_MAX_SCORE = 100.0


@dataclass(frozen=True)
class ScoreBreakdown:
    """All five score components plus the weighted total."""

    relevance: float
    freshness: float
    implementation_evidence: float
    engagement: float
    confidence: float
    total: float
    classification: str


def combine_scores(
    *,
    relevance: float,
    freshness: float,
    implementation_evidence: float,
    engagement: float,
    confidence: float,
    weights: dict[str, float] | None = None,
) -> float:
    """Weighted sum of the five components, clamped to [0, 100]."""
    w = weights or SCORING_WEIGHTS
    total = (
        relevance * w["relevance"]
        + freshness * w["freshness"]
        + implementation_evidence * w["implementation_evidence"]
        + engagement * w["engagement"]
        + confidence * w["uniqueness_confidence"]
    )
    return max(0.0, min(_MAX_SCORE, total))


def classify_evidence(text: str, source_type: str = "repository") -> Classification:
    """Deterministically classify a discovery from its text evidence.

    Uses README/code/description text. Never overclaims: returns
    ``"unknown"`` when evidence is weak. For issue/PR sources without code
    signals, returns ``"discussion"``.
    """
    lowered = text.lower()
    if not lowered.strip():
        return "unknown"

    if "openai-compat" in lowered or "openai compat" in lowered:
        return "openai-compatible"
    if "proxy" in lowered or "proxies" in lowered:
        return "proxy"
    if "gateway" in lowered:
        return "gateway"
    if "sdk" in lowered:
        return "sdk"
    if "wrapper" in lowered:
        return "api-wrapper"
    if "client" in lowered:
        return "client"
    if any(word in lowered for word in ("example", "demo", "sample", "tutorial")):
        return "example"
    if any(word in lowered for word in ("automat", "bot ", " bot", "workflow", "pipeline")):
        return "automation"
    if source_type in ("issue", "pull_request"):
        return "discussion"
    return "unknown"


def score_relevance(matched_terms: list[str], classification: str) -> float:
    """Score how well the result matches the search intent (0-100)."""
    unique_terms = {t.strip().lower() for t in matched_terms if t.strip()}
    score = len(unique_terms) * _RELEVANCE_PER_TERM
    if classification in CLASSIFICATIONS and classification != "unknown":
        score += _RELEVANCE_CLASSIFICATION_BONUS
    return max(0.0, min(_MAX_SCORE, score))


def score_freshness(
    created_at: datetime | None,
    pushed_at: datetime | None,
    lookback_days: int,
    updated_at: datetime | None = None,
    reference: datetime | None = None,
) -> float:
    """Score recency (0-100) from the most recent available timestamp.

    A result with no usable dates scores 0 — unknown dates are never
    treated as fresh.
    """
    candidates = [dt for dt in (created_at, pushed_at, updated_at) if dt is not None]
    if not candidates:
        return 0.0
    most_recent = max(candidates)
    ref = reference if reference is not None else now_utc()
    ensure_utc(ref)
    cutoff = cutoff_utc(lookback_days, reference=ref)
    # Age relative to the reference "now"; future-dated items count as now.
    age_days = max(0.0, (ref - most_recent).total_seconds() / 86400.0)
    if most_recent < cutoff:
        # Stale but known: small residual instead of flat zero so that
        # slightly-out-of-window items still sort deterministically.
        return 5.0
    return max(0.0, min(_MAX_SCORE, 100.0 * (1.0 - age_days / lookback_days)))


def score_implementation_evidence(
    api_patterns: list[str], classification: str
) -> float:
    """Score presence of real API implementation code (0-100).

    A mere provider-name mention scores near zero; actual endpoint/client
    code patterns score high.
    """
    unique_patterns = {p.strip().lower() for p in api_patterns if p.strip()}
    score = len(unique_patterns) * 25.0
    if classification in CLASSIFICATIONS and classification not in ("unknown", "discussion"):
        score += 10.0
    return max(0.0, min(_MAX_SCORE, score))


def score_engagement(stars: int | None, forks: int | None) -> float:
    """Score GitHub engagement (0-100) on a log scale.

    Log scaling keeps viral repos from dwarfing every other signal —
    engagement is only 10% of the total by design.
    """
    import math

    stars = max(0, stars or 0)
    forks = max(0, forks or 0)
    score = 20.0 * math.log10(1 + stars) + 10.0 * math.log10(1 + forks)
    return max(0.0, min(_MAX_SCORE, score))


def score_confidence(
    matched_terms: list[str],
    evidence_count: int,
    has_reliable_dates: bool,
) -> float:
    """Score confidence in the discovery's quality (0-100)."""
    unique_terms = {t.strip().lower() for t in matched_terms if t.strip()}
    score = 30.0 + len(unique_terms) * 10.0 + min(evidence_count, 5) * 6.0
    if has_reliable_dates:
        score += 10.0
    return max(0.0, min(_MAX_SCORE, score))


def score_discovery(
    discovery: object,
    lookback_days: int = 10,
    api_patterns: list[str] | None = None,
    reference: datetime | None = None,
) -> ScoreBreakdown:
    """Score a Discovery and return the full breakdown.

    Accepts a Discovery (or any object with the same attribute names) so
    scoring stays decoupled from model construction order.
    """
    matched = list(getattr(discovery, "matched_terms", []) or [])
    evidence = list(getattr(discovery, "evidence", []) or [])
    classification = str(getattr(discovery, "classification", "unknown"))

    relevance = score_relevance(matched, classification)
    freshness = score_freshness(
        getattr(discovery, "created_at", None),
        getattr(discovery, "pushed_at", None),
        lookback_days,
        updated_at=getattr(discovery, "updated_at", None),
        reference=reference,
    )
    implementation = score_implementation_evidence(api_patterns or [], classification)
    engagement = score_engagement(
        getattr(discovery, "stars", None), getattr(discovery, "forks", None)
    )
    has_dates = (
        getattr(discovery, "created_at", None) is not None
        or getattr(discovery, "pushed_at", None) is not None
    )
    confidence = score_confidence(matched, len(evidence), has_dates)
    total = combine_scores(
        relevance=relevance,
        freshness=freshness,
        implementation_evidence=implementation,
        engagement=engagement,
        confidence=confidence,
    )
    return ScoreBreakdown(
        relevance=relevance,
        freshness=freshness,
        implementation_evidence=implementation,
        engagement=engagement,
        confidence=confidence,
        total=total,
        classification=classification,
    )
