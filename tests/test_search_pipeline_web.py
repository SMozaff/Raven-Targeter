import pytest

from raven_targeter.models import AdapterSearchResult, Discovery, SearchRequest
from raven_targeter.services.search_service import SearchPipeline


class FakeWebAdapter:
    async def search_targets(self, targets, keywords, *, lookback_days, max_results):
        return AdapterSearchResult(
            discoveries=[
                Discovery(
                    source="web_search",
                    source_type="web",
                    provider="openai",
                    title="Web API wrapper",
                    url="https://example.com/project",
                    evidence=["Server-side recency filter: last 10 day(s)", "API wrapper"],
                )
            ]
        )

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_web_only_search_can_run_without_github_adapter():
    request = SearchRequest(
        targets=["openai"],
        sources=[],
        web_search=True,
        lookback_days=10,
        max_results_per_source=20,
    )
    results, errors = await SearchPipeline().run(request, None, FakeWebAdapter())
    assert not errors
    assert len(results) == 1
    assert results[0].source_type == "web"
    assert results[0].freshness_score >= 80
