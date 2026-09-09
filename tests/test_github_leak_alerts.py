"""Tests that GitHubAdapter surfaces LeakAlerts from code enrichment,
without ever putting the raw secret into any Discovery or LeakAlert field."""
from __future__ import annotations

import httpx
import pytest

from raven_targeter.adapters.github import GitHubAdapter
from raven_targeter.models import QueryVariant

_FAKE_OPENAI_KEY = "sk-proj-" + "aB3xY9zQ7mK2wR8tL5vN1pS6dF4hJ0cE"


def _code_search_response() -> dict:
    return {
        "items": [
            {
                "path": "config.py",
                "html_url": "https://github.com/someuser/some-project/blob/main/config.py",
                "repository": {
                    "full_name": "someuser/some-project",
                    "name": "some-project",
                    "owner": {"login": "someuser"},
                },
            }
        ]
    }


@pytest.mark.asyncio
async def test_code_enrichment_produces_leak_alert_without_raw_secret():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/code" in str(request.url):
            return httpx.Response(200, json=_code_search_response())
        if "/repos/someuser/some-project/contents/config.py" in str(request.url):
            return httpx.Response(
                200, text=f'OPENAI_API_KEY = "{_FAKE_OPENAI_KEY}"\n'
            )
        return httpx.Response(404)

    adapter = GitHubAdapter(transport=httpx.MockTransport(handler), max_enrich_per_group=5)
    try:
        result = await adapter.search(
            [QueryVariant(target="openai", search_type="code", query_text="openai")],
            max_results=10,
        )
    finally:
        await adapter.aclose()

    assert not result.errors
    assert len(result.leak_alerts) == 1
    alert = result.leak_alerts[0]
    assert alert.pattern_name == "openai-key"
    assert alert.repo_identity == "github.com/someuser/some-project"
    assert alert.repo_url  # points at the repo/file for human verification
    assert alert.source_file == "config.py"
    assert alert.confidence >= 0.6

    # The raw secret must never appear anywhere in the alert's fields.
    alert_dump = alert.model_dump_json()
    assert _FAKE_OPENAI_KEY not in alert_dump

    # Nor should it leak into the Discovery's own evidence (which goes
    # through redact_text separately, but we check the end-to-end result).
    for discovery in result.discoveries:
        assert _FAKE_OPENAI_KEY not in discovery.model_dump_json()


@pytest.mark.asyncio
async def test_code_enrichment_with_no_secret_produces_no_leak_alert():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/code" in str(request.url):
            return httpx.Response(200, json=_code_search_response())
        if "/repos/someuser/some-project/contents/config.py" in str(request.url):
            return httpx.Response(200, text="def hello():\n    return 'world'\n")
        return httpx.Response(404)

    adapter = GitHubAdapter(transport=httpx.MockTransport(handler), max_enrich_per_group=5)
    try:
        result = await adapter.search(
            [QueryVariant(target="openai", search_type="code", query_text="openai")],
            max_results=10,
        )
    finally:
        await adapter.aclose()

    assert not result.errors
    assert result.leak_alerts == []


@pytest.mark.asyncio
async def test_code_enrichment_placeholder_key_does_not_produce_high_confidence_alert():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/search/code" in str(request.url):
            return httpx.Response(200, json=_code_search_response())
        if "/repos/someuser/some-project/contents/config.py" in str(request.url):
            return httpx.Response(
                200, text='OPENAI_API_KEY = "sk-your_key_here_placeholder_padding"\n'
            )
        return httpx.Response(404)

    adapter = GitHubAdapter(transport=httpx.MockTransport(handler), max_enrich_per_group=5)
    try:
        result = await adapter.search(
            [QueryVariant(target="openai", search_type="code", query_text="openai")],
            max_results=10,
        )
    finally:
        await adapter.aclose()

    assert not result.errors
    # high_confidence_findings filters suppressed placeholder matches out,
    # so no alert should surface for an obvious placeholder key.
    assert result.leak_alerts == []
