import httpx
import pytest

from raven_targeter.adapters.serpapi import SerpAPIAdapter


@pytest.mark.asyncio
async def test_serpapi_search_uses_key_in_request_and_normalizes_results():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "title": "Example AI wrapper",
                        "link": "https://api.example.com/v1",
                        "snippet": "Public API endpoint https://api.example.com/v1",
                    }
                ]
            },
        )

    adapter = SerpAPIAdapter(
        "secret-key",
        engine="google",
        max_queries=1,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await adapter.search_targets(
            ["openai"], [], lookback_days=10, max_results=10
        )
    finally:
        await adapter.aclose()

    assert not result.errors
    assert len(result.discoveries) == 1
    discovery = result.discoveries[0]
    assert discovery.source_type == "web"
    assert discovery.source == "web_search"
    assert discovery.candidate_endpoints
    assert "api_key=secret-key" in seen["url"]
    assert "tbs=qdr%3Ad10" in seen["url"] or "tbs=qdr:d10" in seen["url"]


@pytest.mark.asyncio
async def test_serpapi_error_is_explicit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key"})

    adapter = SerpAPIAdapter("bad", max_queries=1, transport=httpx.MockTransport(handler))
    try:
        result = await adapter.search_targets(
            ["openai"], [], lookback_days=10, max_results=10
        )
    finally:
        await adapter.aclose()

    assert result.errors
    assert result.errors[0].status_code == 401
    assert "invalid api key" in result.errors[0].message
