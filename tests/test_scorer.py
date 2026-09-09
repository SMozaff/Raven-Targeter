"""Tests for core/scorer.py: weights, components, classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from raven_targeter.core.scorer import (
    SCORING_WEIGHTS,
    classify_evidence,
    combine_scores,
    score_confidence,
    score_discovery,
    score_engagement,
    score_freshness,
    score_implementation_evidence,
    score_relevance,
)
from raven_targeter.models import Discovery


def _ref() -> datetime:
    return datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def test_weights_sum_to_one():
    assert abs(sum(SCORING_WEIGHTS.values()) - 1.0) < 1e-9
    assert set(SCORING_WEIGHTS) == {
        "relevance",
        "freshness",
        "implementation_evidence",
        "engagement",
        "uniqueness_confidence",
    }


def test_combine_scores_weighted_math():
    total = combine_scores(
        relevance=100.0,
        freshness=100.0,
        implementation_evidence=100.0,
        engagement=100.0,
        confidence=100.0,
    )
    assert total == 100.0
    zero = combine_scores(
        relevance=0.0,
        freshness=0.0,
        implementation_evidence=0.0,
        engagement=0.0,
        confidence=0.0,
    )
    assert zero == 0.0


def test_relevance_grows_with_terms_and_classification():
    weak = score_relevance(["claude"], "unknown")
    strong = score_relevance(["claude", "wrapper", "proxy"], "proxy")
    assert strong > weak > 0


def test_relevance_empty_is_zero():
    assert score_relevance([], "unknown") == 0.0


def test_implementation_evidence_outranks_mention_only():
    mention = score_implementation_evidence([], "unknown")
    impl = score_implementation_evidence(["fastapi", "httpx", "/v1/"], "api-wrapper")
    assert impl > mention
    assert mention == 0.0


def test_freshness_recent_scores_high():
    ref = _ref()
    score = score_freshness(
        ref - timedelta(days=1), ref - timedelta(days=1), 10, reference=ref
    )
    assert score > 80.0


def test_freshness_stale_is_residual():
    ref = _ref()
    score = score_freshness(
        ref - timedelta(days=200), ref - timedelta(days=200), 10, reference=ref
    )
    assert score == 5.0


def test_freshness_unknown_dates_is_zero():
    assert score_freshness(None, None, 10, reference=_ref()) == 0.0


def test_engagement_log_scaled_and_capped():
    assert score_engagement(None, None) == 0.0
    assert score_engagement(0, 0) == 0.0
    mid = score_engagement(100, 10)
    high = score_engagement(100000, 20000)
    assert 0 < mid < high <= 100.0


def test_confidence_dates_add_points():
    without = score_confidence(["claude"], 2, False)
    with_dates = score_confidence(["claude"], 2, True)
    assert with_dates > without


def test_classify_proxy():
    assert classify_evidence("A fast Claude API proxy server") == "proxy"


def test_classify_openai_compatible_first():
    text = "An OpenAI-compatible proxy gateway for Claude"
    assert classify_evidence(text) == "openai-compatible"


def test_classify_weak_evidence_is_unknown():
    assert classify_evidence("some random weekend project") == "unknown"
    assert classify_evidence("") == "unknown"
    assert classify_evidence("   ") == "unknown"


def test_classify_issue_without_code_is_discussion():
    assert classify_evidence("Claude API keeps timing out", "issue") == "discussion"


def test_score_discovery_total_matches_components():
    ref = _ref()
    d = Discovery(
        title="claude proxy",
        url="https://github.com/foo/bar",
        created_at=ref - timedelta(days=1),
        pushed_at=ref - timedelta(hours=5),
        stars=50,
        forks=5,
        matched_terms=["claude", "proxy"],
        evidence=["FastAPI endpoint present"],
        classification="proxy",
    )
    breakdown = score_discovery(d, 10, api_patterns=["fastapi", "/v1/"], reference=ref)
    expected = combine_scores(
        relevance=breakdown.relevance,
        freshness=breakdown.freshness,
        implementation_evidence=breakdown.implementation_evidence,
        engagement=breakdown.engagement,
        confidence=breakdown.confidence,
    )
    assert breakdown.total == expected
    assert breakdown.classification == "proxy"


def test_implementation_beats_mention_only_end_to_end():
    ref = _ref()
    impl = Discovery(
        title="claude FastAPI wrapper",
        url="https://github.com/foo/impl",
        created_at=ref - timedelta(days=2),
        pushed_at=ref - timedelta(days=1),
        matched_terms=["claude", "wrapper"],
        evidence=["FastAPI endpoint present", "httpx client found"],
        classification="api-wrapper",
    )
    mention = Discovery(
        title="someone mentions claude",
        url="https://github.com/foo/mention",
        created_at=ref - timedelta(days=2),
        pushed_at=ref - timedelta(days=1),
        matched_terms=["claude"],
        evidence=[],
        classification="unknown",
    )
    impl_total = score_discovery(
        impl, 10, api_patterns=["fastapi", "httpx"], reference=ref
    ).total
    mention_total = score_discovery(mention, 10, api_patterns=[], reference=ref).total
    assert impl_total > mention_total
