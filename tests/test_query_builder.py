from datetime import UTC, datetime
from raven_targeter.core.query_builder import build_queries
from raven_targeter.models import SearchRequest


def test_repository_search_has_created_and_pushed_axes():
    req = SearchRequest(targets=["openai"], sources=["repository"], lookback_days=10)
    qs = build_queries(req, datetime(2026, 9, 9, tzinfo=UTC))
    axes = {q.freshness_axis for q in qs}
    assert {"created", "pushed"} <= axes
    assert any("created" in q.qualifiers for q in qs)
    assert any("pushed" in q.qualifiers for q in qs)


def test_code_search_has_no_date_qualifier():
    qs = build_queries(SearchRequest(targets=["openai"], sources=["code"]))
    assert qs and all(not q.qualifiers for q in qs)
