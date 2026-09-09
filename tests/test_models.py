"""Tests for models.py: Discovery, SearchRequest, QueryVariant."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from raven_targeter.models import Discovery, QueryVariant, SearchRequest


def test_search_request_defaults_match_spec():
    req = SearchRequest()
    assert req.targets == ["openai", "anthropic", "gemini", "grok", "deepseek"]
    assert req.keywords == []
    assert req.lookback_days == 10
    assert req.max_results_per_source == 200
    assert req.minimum_score == 0.0


def test_search_request_normalizes_targets():
    req = SearchRequest(targets=["OpenAI", " ANTHROPIC ", "gemini"])
    assert req.targets == ["openai", "anthropic", "gemini"]


def test_search_request_rejects_bad_lookback():
    with pytest.raises(ValidationError):
        SearchRequest(lookback_days=0)
    with pytest.raises(ValidationError):
        SearchRequest(lookback_days=366)


def test_discovery_minimal():
    d = Discovery(title="x", url="https://github.com/foo/bar")
    assert d.classification == "unknown"
    assert d.relevance_score == 0.0
    assert d.matched_terms == []
    assert d.evidence == []
    assert d.discovered_at.tzinfo is not None


def test_discovery_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        Discovery(
            title="x",
            url="https://github.com/foo/bar",
            created_at=datetime(2026, 1, 1),
        )


def test_discovery_accepts_utc_datetimes():
    d = Discovery(
        title="x",
        url="https://github.com/foo/bar",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    assert d.created_at == datetime(2026, 9, 1, tzinfo=UTC)


def test_discovery_normalizes_provider():
    d = Discovery(title="x", url="https://github.com/foo/bar", provider="Claude")
    assert d.provider == "claude"


def test_total_score_zero_when_all_components_zero():
    d = Discovery(title="x", url="https://github.com/foo/bar")
    assert d.total_score == 0.0


def test_total_score_hundred_when_all_components_hundred():
    d = Discovery(
        title="x",
        url="https://github.com/foo/bar",
        relevance_score=100.0,
        freshness_score=100.0,
        implementation_score=100.0,
        engagement_score=100.0,
        confidence_score=100.0,
    )
    assert d.total_score == pytest.approx(100.0)


def test_query_variant_dedup_key_stable():
    q1 = QueryVariant(target="OpenAI", search_type="repository", query_text='"OpenAI" wrapper')
    q2 = QueryVariant(target="openai", search_type="repository", query_text='"OpenAI" wrapper')
    assert q1.target == "openai"
    assert q1.dedup_key == q2.dedup_key
