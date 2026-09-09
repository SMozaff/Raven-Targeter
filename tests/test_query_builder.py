"""Tests for core/query_builder.py."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from raven_targeter.config.aliases import get_aliases
from raven_targeter.core.query_builder import build_queries
from raven_targeter.models import SearchRequest


def _ref() -> datetime:
    return datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def test_build_queries_covers_all_default_targets():
    queries = build_queries(SearchRequest(), reference=_ref())
    assert queries, "expected queries for default targets"
    covered = {q.target for q in queries}
    assert covered == set(SearchRequest().targets)


def test_query_count_bounded():
    queries = build_queries(SearchRequest(), reference=_ref())
    # 22 per target max x 5 targets = 110; allow headroom but never hundreds.
    assert len(queries) <= 130


def test_queries_deduplicated():
    queries = build_queries(SearchRequest(), reference=_ref())
    keys = [q.dedup_key for q in queries]
    assert len(keys) == len(set(keys))


def test_repo_variants_carry_created_qualifier():
    queries = build_queries(
        SearchRequest(targets=["openai"], sources=["repository"]), reference=_ref()
    )
    assert queries
    for q in queries:
        assert q.qualifiers.get("created") == ">=2026-08-30"


def test_code_variants_carry_no_date_qualifiers():
    queries = build_queries(
        SearchRequest(targets=["openai"], sources=["code"]), reference=_ref()
    )
    assert queries
    for q in queries:
        assert q.qualifiers == {}, "code search must not carry date qualifiers"


def test_sources_filter_limits_search_types():
    queries = build_queries(
        SearchRequest(targets=["openai"], sources=["repository"]), reference=_ref()
    )
    assert {q.search_type for q in queries} == {"repository"}


def test_keywords_appended_to_query_text():
    queries = build_queries(
        SearchRequest(targets=["openai"], keywords=["fastapi"], sources=["repository"]),
        reference=_ref(),
    )
    assert queries
    assert all('"fastapi"' in q.query_text for q in queries)


def test_unicode_keywords_preserved():
    queries = build_queries(
        SearchRequest(targets=["gemini"], keywords=["日本語"], sources=["repository"]),
        reference=_ref(),
    )
    assert queries
    assert all("日本語" in q.query_text for q in queries)


def test_unknown_target_raises():
    with pytest.raises(ValueError):
        build_queries(SearchRequest(targets=["mistral"]), reference=_ref())


def test_query_text_pairs_name_with_intent():
    queries = build_queries(
        SearchRequest(targets=["anthropic"], sources=["repository"]), reference=_ref()
    )
    names = get_aliases("anthropic").names
    assert any(any(n in q.query_text for n in names) for q in queries)
