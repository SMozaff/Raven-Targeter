"""Tests for the GitHub adapter — all HTTP is mocked, no live GitHub access.

Covers: success normalization, 401/403/422/429/5xx handling, retry
behavior, timeouts, malformed JSON, partial failure, missing token,
Unicode queries, README enrichment/redaction, and the disabled Gist
placeholder.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from raven_targeter.adapters.base import SearchError
from raven_targeter.adapters.github import (
    README_MAX_CHARS,
    GitHubAdapter,
    build_q,
)
from raven_targeter.adapters.github_gists import GitHubGistAdapter
from raven_targeter.models import QueryVariant


def _query(
    target: str = "openai",
    search_type: str = "repository",
    text: str = '"OpenAI" wrapper',
    qualifiers: dict[str, str] | None = None,
) -> QueryVariant:
    return QueryVariant(
        target=target,  # type: ignore[arg-type]
        search_type=search_type,  # type: ignore[arg-type]
        query_text=text,
        qualifiers=qualifiers
        if qualifiers is not None
        else {"created": ">=2026-08-30"},
    )


def _repo_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": "cool-wrapper",
        "full_name": "someone/cool-wrapper",
        "owner": {"login": "someone"},
        "html_url": "https://github.com/someone/cool-wrapper",
        "description": "An OpenAI API wrapper",
        "stargazers_count": 42,
        "forks_count": 7,
        "created_at": "2026-09-05T10:00:00Z",
        "updated_at": "2026-09-06T10:00:00Z",
        "pushed_at": "2026-09-07T10:00:00Z",
    }
    item.update(overrides)
    return item


def _search_response(items: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"total_count": len(items), "items": items})


class _Harness:
    """Mock-transport adapter with captured requests and sleep calls."""

    def __init__(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        **adapter_kwargs: Any,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        def wrapped(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        kwargs = {
            "token": "test-token-abc",
            "retry_wait_initial": 0.01,
            "max_readme_enrich": 0,
            **adapter_kwargs,
        }
        self.adapter = GitHubAdapter(
            transport=httpx.MockTransport(wrapped),
            sleep_fn=fake_sleep,
            **kwargs,
        )

    async def aclose(self) -> None:
        await self.adapter.aclose()


# -- success paths -------------------------------------------------------


async def test_repo_search_success_normalizes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/repositories"
        return _search_response([_repo_item()])

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert result.errors == []
    assert len(result.discoveries) == 1
    d = result.discoveries[0]
    assert d.source == "github"
    assert d.source_type == "repository"
    assert d.provider == "openai"
    assert d.title == "someone/cool-wrapper"
    assert d.url == "https://github.com/someone/cool-wrapper"
    assert d.author == "someone"
    assert d.created_at is not None and d.created_at.tzinfo is not None
    assert d.stars == 42
    assert d.forks == 7
    assert d.canonical_url == "https://github.com/someone/cool-wrapper"
    assert d.repo_identity == "github.com/someone/cool-wrapper"
    assert "openai" in [t.lower() for t in d.matched_terms]
    assert "wrapper" in [t.lower() for t in d.matched_terms]


async def test_q_param_uses_params_not_url_concat():
    def handler(request: httpx.Request) -> httpx.Response:
        # The q value must arrive as a proper query param...
        assert "wrapper" in request.url.params["q"]
        assert "created:>=2026-08-30" in request.url.params["q"]
        # ...while the path itself carries no query text.
        assert "?" not in request.url.path
        return _search_response([])

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()
    assert result.errors == []


async def test_missing_token_sends_no_auth_header():
    seen: dict[str, bool] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["has_auth"] = "authorization" in request.headers
        return _search_response([])

    harness = _Harness(handler, token=None)
    assert harness.adapter.is_authenticated is False
    try:
        await harness.adapter.search([_query()])
    finally:
        await harness.aclose()
    assert seen["has_auth"] is False


async def test_authenticated_sends_bearer_header():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return _search_response([])

    harness = _Harness(handler)
    assert harness.adapter.is_authenticated is True
    try:
        await harness.adapter.search([_query()])
    finally:
        await harness.aclose()
    assert seen["auth"] == "Bearer test-token-abc"


# -- error statuses -------------------------------------------------------


async def test_401_error_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert result.discoveries == []
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.status_code == 401
    assert "Bad credentials" in err.message
    assert err.retryable is False
    assert len(harness.requests) == 1  # no retry


async def test_403_forbidden_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"message": "Resource not accessible by integration"}
        )

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert result.discoveries == []
    assert len(harness.requests) == 1
    assert result.errors[0].retryable is False
    assert result.errors[0].status_code == 403


async def test_403_rate_limited_retries_after_wait():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                403,
                headers={"retry-after": "5"},
                json={"message": "API rate limit exceeded"},
            )
        return _search_response([_repo_item()])

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert len(harness.requests) == 2
    assert harness.sleeps == [5.0]  # Retry-After honored, no real waiting
    assert len(result.discoveries) == 1
    assert result.errors == []


async def test_422_not_retried_with_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "message": "Validation Failed",
                "errors": [{"message": "The listed users cannot be searched"}],
            },
        )

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert len(harness.requests) == 1
    assert result.errors[0].status_code == 422
    assert result.errors[0].retryable is False
    assert "listed users" in result.errors[0].message


async def test_429_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "Too Many Requests"})
        return _search_response([_repo_item()])

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert len(harness.requests) == 2
    assert len(result.discoveries) == 1
    assert result.errors == []


async def test_503_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"message": "Service Unavailable"})
        return _search_response([])

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert len(harness.requests) == 2
    assert result.errors == []


async def test_persistent_500_exhausts_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "Server Error"})

    harness = _Harness(handler, max_attempts=3)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert len(harness.requests) == 3  # bounded: 1 + 2 retries
    assert result.discoveries == []
    assert len(result.errors) == 1
    assert result.errors[0].status_code == 500
    assert result.errors[0].retryable is True
    assert "retries exhausted" in result.errors[0].message


async def test_timeout_retries_then_records_retryable_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("connection timed out")

    harness = _Harness(handler, max_attempts=2)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert calls["n"] == 2
    assert result.discoveries == []
    assert len(result.errors) == 1
    assert result.errors[0].status_code is None
    assert result.errors[0].retryable is True
    assert "timed out" in result.errors[0].message


async def test_malformed_json_recorded_not_retried():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{this is not json")

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert len(harness.requests) == 1
    assert result.discoveries == []
    assert len(result.errors) == 1
    assert "Malformed JSON" in result.errors[0].message
    assert result.errors[0].retryable is False


async def test_partial_failure_keeps_good_results():
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params.get("q", "")
        if "wrapper" in q:
            return _search_response([_repo_item()])
        return httpx.Response(403, json={"message": "Forbidden resource"})

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search(
            [_query(text='"OpenAI" wrapper'), _query(text='"ChatGPT" SDK')]
        )
    finally:
        await harness.aclose()

    assert len(result.discoveries) == 1
    assert len(result.errors) == 1
    assert result.errors[0].status_code == 403


# -- search-type specifics -------------------------------------------------


async def test_issue_search_injects_type_issue():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params["q"]
        return _search_response(
            [
                {
                    "title": "Claude wrapper crashes",
                    "body": "The unofficial Claude API wrapper fails on auth",
                    "html_url": "https://github.com/someone/w/issues/3",
                    "user": {"login": "reporter"},
                    "created_at": "2026-09-04T10:00:00Z",
                    "updated_at": "2026-09-05T10:00:00Z",
                    "repository_url": "https://api.github.com/repos/someone/w",
                }
            ]
        )

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search(
            [_query(search_type="issue", text='"Claude" wrapper')]
        )
    finally:
        await harness.aclose()

    assert "type:issue" in captured["q"]
    assert len(result.discoveries) == 1
    d = result.discoveries[0]
    assert d.source_type == "issue"
    assert d.repo_identity == "github.com/someone/w"
    assert d.pushed_at is None  # issues have no pushed_at; never conflated


async def test_pr_search_injects_type_pr_and_detects_pr():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params["q"]
        return _search_response(
            [
                {
                    "title": "Add Gemini proxy support",
                    "body": "proxy implementation",
                    "html_url": "https://github.com/someone/w/pull/9",
                    "user": {"login": "contrib"},
                    "created_at": "2026-09-04T10:00:00Z",
                    "updated_at": "2026-09-05T10:00:00Z",
                    "repository_url": "https://api.github.com/repos/someone/w",
                    "pull_request": {"url": "https://api.github.com/x"},
                }
            ]
        )

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search(
            [_query(target="gemini", search_type="pull_request",
                    text='"Gemini" proxy')]
        )
    finally:
        await harness.aclose()

    assert "type:pr" in captured["q"]
    assert result.discoveries[0].source_type == "pull_request"
    assert result.discoveries[0].provider == "gemini"


async def test_code_search_carries_no_date_qualifier():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params["q"]
        return _search_response(
            [
                {
                    "path": "client.py",
                    "html_url": "https://github.com/o/r/blob/main/client.py",
                    "repository": {
                        "full_name": "o/r",
                        "name": "r",
                        "owner": {"login": "o"},
                    },
                }
            ]
        )

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search(
            [_query(search_type="code", text='"Claude" wrapper', qualifiers={})]
        )
    finally:
        await harness.aclose()

    assert "created" not in captured["q"]
    assert len(result.discoveries) == 1
    d = result.discoveries[0]
    assert d.source_type == "code"
    assert d.repo_identity == "github.com/o/r"
    assert d.created_at is None  # code hits carry no dates of their own


async def test_unicode_query_preserved():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["q"] = request.url.params["q"]
        return _search_response([])

    harness = _Harness(handler)
    try:
        # The builder folds user keywords into query_text; the adapter must
        # transmit them intact as a proper q param (httpx handles encoding).
        await harness.adapter.search(
            [_query(target="gemini", text='"Gemini" wrapper "日本語プロキシ"')]
        )
    finally:
        await harness.aclose()

    assert "日本語プロキシ" in captured["q"]


def test_build_q_sorts_qualifiers_deterministically():
    q = _query(
        search_type="issue",
        text='"X" y',
        qualifiers={"created": ">=2026-08-30", "stars": ">10"},
    )
    assert build_q(q) == '"X" y created:>=2026-08-30 stars:>10 type:issue'


# -- README enrichment -------------------------------------------------------


async def test_readme_enrichment_redacts_and_truncates():
    secret = "sk-abc123XYZ4567890"
    long_readme = ("# Wrapper\nUses openai client. Key example: " + secret + "\n") + (
        "x" * 5000
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return _search_response([_repo_item()])
        assert request.url.path == "/repos/someone/cool-wrapper/readme"
        return httpx.Response(200, text=long_readme)

    harness = _Harness(handler, max_readme_enrich=10)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert result.errors == []
    d = result.discoveries[0]
    readme_notes = [e for e in d.evidence if e.startswith("README excerpt: ")]
    assert len(readme_notes) == 1
    assert secret not in readme_notes[0]
    assert "[REDACTED_API_KEY]" in readme_notes[0]
    assert len(readme_notes[0]) <= len("README excerpt: ") + README_MAX_CHARS


async def test_readme_404_keeps_discovery_with_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return _search_response([_repo_item()])
        return httpx.Response(404, json={"message": "Not Found"})

    harness = _Harness(handler, max_readme_enrich=10)
    try:
        result = await harness.adapter.search([_query()])
    finally:
        await harness.aclose()

    assert len(result.discoveries) == 1
    assert len(result.errors) == 1
    assert result.errors[0].source == "github:readme"
    assert result.errors[0].status_code == 404


# -- Gist placeholder ----------------------------------------------------------


async def test_gist_adapter_disabled_by_default():
    adapter = GitHubGistAdapter()
    assert adapter.enabled is False
    result = await adapter.search([_query()])
    assert result.discoveries == []
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], SearchError)
    assert "disabled" in result.errors[0].message.lower()
    await adapter.aclose()


async def test_adapter_from_settings_picks_up_token():
    from raven_targeter.config.settings import Settings

    settings = Settings(_env_file=None, github_token="ghp_fromsettings123")
    adapter = GitHubAdapter.from_settings(settings)
    assert adapter.is_authenticated is True
    await adapter.aclose()

    anonymous = GitHubAdapter.from_settings(Settings(_env_file=None))
    assert anonymous.is_authenticated is False
    await anonymous.aclose()


@pytest.mark.asyncio
async def test_max_results_caps_discoveries():
    items = [
        _repo_item(name=f"r{i}", full_name=f"o/r{i}",
                   html_url=f"https://github.com/o/r{i}")
        for i in range(5)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return _search_response(items)

    harness = _Harness(handler)
    try:
        result = await harness.adapter.search(
            [_query(), _query(text='"ChatGPT" SDK')], max_results=3
        )
    finally:
        await harness.aclose()

    assert len(result.discoveries) == 3
