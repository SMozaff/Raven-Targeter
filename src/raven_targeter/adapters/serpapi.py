"""Optional SerpAPI-backed public web discovery adapter.

The key is provided at runtime from the user's OS keychain. It is never
persisted in Raven's database or result exports.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from dateutil import parser as date_parser

from raven_targeter.core.endpoint_extractor import extract_candidate_endpoints
from raven_targeter.core.web_query_builder import build_web_queries
from raven_targeter.models import AdapterSearchResult, Discovery, SearchError
from raven_targeter.utils.urls import canonicalize_url


class SerpAPIAdapter:
    name = "serpapi"

    def __init__(
        self,
        api_key: str,
        *,
        engine: str = "google",
        base_url: str = "https://serpapi.com/search.json",
        timeout: float = 20.0,
        max_queries: int = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        if not self.api_key:
            raise ValueError("Search API key is required")
        self.engine = engine.strip().lower() or "google"
        self.base_url = base_url
        self.timeout = timeout
        self.max_queries = max_queries
        self.transport = transport
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                headers={"User-Agent": "Raven-Targeter/0.3"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def test_connection(self) -> tuple[bool, str]:
        """Perform one minimal real search. This may consume one API request."""
        params = self._params("Raven-Targeter API test", lookback_days=1, num=1)
        try:
            response = await self._get_client().get(self.base_url, params=params)
        except httpx.HTTPError as exc:
            return False, f"Search API network error: {type(exc).__name__}"
        if response.status_code != 200:
            return False, self._error_message(response)
        try:
            body = response.json()
        except ValueError:
            return False, "Search API returned malformed JSON"
        if isinstance(body, dict) and body.get("error"):
            return False, str(body["error"])[:400]
        return True, f"Connected to SerpAPI ({self.engine})"

    def _params(self, query: str, *, lookback_days: int, num: int = 10) -> dict[str, Any]:
        params: dict[str, Any] = {
            "engine": self.engine,
            "q": query,
            "api_key": self.api_key,
            "num": max(1, min(num, 20)),
        }
        # Google's qdr filter is a real server-side recency filter. Other
        # SerpAPI engines have different date controls, so their recency is
        # best-effort and is not falsely represented as a publication date.
        if self.engine == "google":
            params["tbs"] = f"qdr:d{max(1, lookback_days)}"
        return params

    async def search_targets(
        self,
        targets: list[str],
        keywords: list[str],
        *,
        lookback_days: int,
        max_results: int,
    ) -> AdapterSearchResult:
        discoveries: list[Discovery] = []
        errors: list[SearchError] = []
        queries = build_web_queries(targets, keywords, max_queries=self.max_queries)
        for target, query in queries:
            if len(discoveries) >= max_results:
                break
            try:
                response = await self._get_client().get(
                    self.base_url,
                    params=self._params(query, lookback_days=lookback_days),
                )
            except httpx.HTTPError as exc:
                errors.append(
                    SearchError(
                        source="serpapi:web",
                        message=f"Search API network error: {type(exc).__name__}",
                        retryable=True,
                    )
                )
                continue
            if response.status_code != 200:
                errors.append(
                    SearchError(
                        source="serpapi:web",
                        status_code=response.status_code,
                        message=self._error_message(response),
                        retryable=response.status_code in {429, 500, 502, 503, 504},
                    )
                )
                continue
            try:
                payload = response.json()
            except ValueError as exc:
                errors.append(
                    SearchError(source="serpapi:web", status_code=200, message=f"Malformed JSON: {exc}")
                )
                continue
            if isinstance(payload, dict) and payload.get("error"):
                errors.append(SearchError(source="serpapi:web", message=str(payload["error"])[:500]))
                continue

            items: list[dict[str, Any]] = []
            if isinstance(payload, dict):
                for key in ("organic_results", "news_results"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        items.extend(x for x in value if isinstance(x, dict))

            for item in items:
                if len(discoveries) >= max_results:
                    break
                link = item.get("link")
                if not isinstance(link, str) or not link.startswith(("http://", "https://")):
                    continue
                title = str(item.get("title") or link)
                snippet = str(item.get("snippet") or item.get("snippet_highlighted_words") or "")
                date_value = self._parse_date(item.get("date"))
                evidence = [f"SerpAPI/{self.engine} query: {query}"]
                if self.engine == "google":
                    evidence.append(f"Server-side recency filter: last {lookback_days} day(s)")
                endpoints = extract_candidate_endpoints(
                    f"{link}\n{snippet}", source_file=f"SerpAPI/{self.engine}"
                )
                discoveries.append(
                    Discovery(
                        source="web_search",
                        source_type="web",
                        provider=target,
                        title=title,
                        url=link,
                        canonical_url=canonicalize_url(link),
                        created_at=date_value,
                        description=snippet[:2000] or None,
                        evidence=evidence,
                        candidate_endpoints=endpoints,
                    )
                )
        return AdapterSearchResult(discoveries=discoveries, errors=errors)

    @staticmethod
    def _parse_date(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = date_parser.parse(value)
        except (ValueError, TypeError, OverflowError):
            return None
        if parsed.tzinfo is None:
            return None
        return parsed

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                if body.get("error"):
                    return str(body["error"])[:500]
                if body.get("message"):
                    return str(body["message"])[:500]
        except ValueError:
            pass
        return f"Search API HTTP {response.status_code}"
