"""GitHub search adapter: repositories, code, issues, PRs, README enrichment.

Uses the GitHub REST search APIs correctly:

- Repository search carries ``created:>=YYYY-MM-DD`` qualifiers (supplied
  by the query builder as structured data).
- Code search carries **no** date qualifiers — the API does not support
  them. Code hits provide implementation evidence linked to their parent
  repository; they carry no dates of their own.
- Issue/PR search goes through ``/search/issues`` with a ``type:issue`` /
  ``type:pr`` qualifier injected here (adapter concern, GitHub syntax).

All HTTP goes through httpx with ``params={...}`` — query URLs are never
built by string concatenation. Failures surface as explicit
:class:`~raven_targeter.adapters.base.SearchError` records; HTTP errors
are never silently treated as zero results.

Retry policy (tenacity, bounded exponential backoff + jitter):

- Retried: 429, 500/502/503/504, rate-limit 403s, timeouts, connection
  errors. ``Retry-After`` / ``x-ratelimit-reset`` hints are honored
  (capped) before retrying.
- Never retried: 401, 422, non-rate-limit 403s, malformed JSON.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from raven_targeter.adapters.base import (
    AdapterSearchResult,
    SearchAdapter,
    SearchError,
)
from raven_targeter.config.settings import Settings
from raven_targeter.core.sanitizer import (
    find_matched_terms,
    redact_text,
)
from raven_targeter.models import Discovery, QueryVariant
from raven_targeter.utils.dates import parse_github_timestamp
from raven_targeter.utils.urls import canonical_repo_identity, canonicalize_url

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.github.com"

_ENDPOINTS = {
    "repository": "/search/repositories",
    "code": "/search/code",
    "issue": "/search/issues",
    "pull_request": "/search/issues",
}

_DEFAULT_TIMEOUT = 15.0
_DEFAULT_MAX_ATTEMPTS = 4  # 1 initial try + 3 retries
_DEFAULT_PER_PAGE = 30
_DEFAULT_MAX_README_ENRICH = 10
README_MAX_CHARS = 2000
DESCRIPTION_MAX_CHARS = 1000
# Upper bound on sleeping for a server-provided rate-limit wait. Longer
# waits surface as an error instead so background workers never hang.
MAX_RATE_LIMIT_WAIT_SECONDS = 120.0


class _RetryableHttpError(Exception):
    """Internal signal: the request failed transiently and may be retried."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        wait_hint: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.wait_hint = wait_hint


class _NonRetryableWrapper(Exception):
    """Internal: a retryable-looking failure that must NOT be retried
    (e.g. a rate-limit wait beyond the cap). Carries the inner error."""

    def __init__(self, inner: _RetryableHttpError) -> None:
        super().__init__(inner.message)
        self.inner = inner


def build_q(query: QueryVariant) -> str:
    """Assemble the GitHub ``q`` parameter from keyword text + qualifiers.

    Type qualifiers for issue/PR search are injected here since they are
    GitHub-search syntax (adapter concern), not generic query-builder data.
    """
    parts = [query.query_text]
    qualifiers = dict(query.qualifiers)
    if query.search_type == "issue":
        qualifiers.setdefault("type", "issue")
    elif query.search_type == "pull_request":
        qualifiers.setdefault("type", "pr")
    for key in sorted(qualifiers):
        parts.append(f"{key}:{qualifiers[key]}")
    return " ".join(parts).strip()


def _rate_limit_wait_seconds(response: httpx.Response) -> float:
    """Seconds until retry per Retry-After / x-ratelimit-reset, else 0."""
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return 0.0
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset")
        if reset is not None:
            try:
                return max(0.0, float(reset) - time.time() + 1.0)
            except ValueError:
                return 0.0
    return 0.0


def _is_rate_limited(response: httpx.Response) -> bool:
    """True if a 403 is a rate-limit response (retryable) rather than a
    genuine permission denial."""
    if response.headers.get("retry-after") is not None:
        return True
    if response.headers.get("x-ratelimit-remaining") == "0":
        return True
    try:
        body = response.json()
    except ValueError:
        return False
    message = str(body.get("message", "")).lower() if isinstance(body, dict) else ""
    return "rate limit" in message or "abuse" in message


class GitHubAdapter(SearchAdapter):
    """Authenticated GitHub search client."""

    name = "github"
    enabled = True

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        per_page: int = _DEFAULT_PER_PAGE,
        max_readme_enrich: int = _DEFAULT_MAX_README_ENRICH,
        transport: httpx.AsyncHTTPTransport | None = None,
        sleep_fn: Callable[[float], Any] | None = None,
        retry_wait_initial: float = 1.0,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._per_page = per_page
        self._max_readme_enrich = max_readme_enrich
        self._transport = transport
        self._sleep_fn = sleep_fn or asyncio.sleep
        self._retry_wait_initial = retry_wait_initial
        self._client: httpx.AsyncClient | None = None
        self._remaining: int | None = None
        self._reset_at: float | None = None

    @classmethod
    def from_settings(
        cls, settings: Settings, **overrides: Any
    ) -> GitHubAdapter:
        """Build an adapter from app settings (token picked up, never logged)."""
        return cls(token=settings.github_token, **overrides)

    @property
    def is_authenticated(self) -> bool:
        """True when an API token is configured (higher rate limits)."""
        return bool(self._token and self._token.strip())

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": "Raven-Targeter/0.1.0",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self.is_authenticated and self._token is not None:
                headers["Authorization"] = f"Bearer {self._token.strip()}"
            self._client = httpx.AsyncClient(
                base_url=API_BASE_URL,
                headers=headers,
                timeout=self._timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- rate limits ----------------------------------------------------

    def _record_rate_limit_headers(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        if remaining is not None:
            try:
                self._remaining = int(remaining)
            except ValueError:
                self._remaining = None
        if reset is not None:
            try:
                self._reset_at = float(reset)
            except ValueError:
                self._reset_at = None

    async def _respect_known_rate_limit(self) -> None:
        """Sleep if a previous response told us the quota is exhausted."""
        if self._remaining == 0 and self._reset_at is not None:
            wait = self._reset_at - time.time() + 1.0
            if wait > MAX_RATE_LIMIT_WAIT_SECONDS:
                logger.warning(
                    "GitHub rate limit exhausted; reset in %.0fs exceeds cap",
                    wait,
                )
                return
            if wait > 0:
                logger.info("GitHub rate limit exhausted; waiting %.0fs", wait)
                await self._sleep_fn(wait)
            self._remaining = None

    # -- request pipeline -----------------------------------------------

    def _classify_response(self, response: httpx.Response) -> str:
        """Return 'ok', 'retry', or 'fail' for a response status."""
        status = response.status_code
        if status == 200:
            return "ok"
        if status == 429:
            return "retry"
        if status in (500, 502, 503, 504):
            return "retry"
        if status == 403:
            return "retry" if _is_rate_limited(response) else "fail"
        return "fail"

    def _describe_error(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return f"GitHub API error {response.status_code} (unparseable body)"
        if isinstance(body, dict):
            message = str(body.get("message", "")).strip()
            errors = body.get("errors", [])
            if isinstance(errors, list) and errors:
                details = "; ".join(
                    str(e.get("message", e)) for e in errors[:3] if isinstance(e, dict)
                ) or str(errors[0])[:200]
                message = f"{message}: {details}" if message else details
            if message:
                return message[:500]
        return f"GitHub API error {response.status_code}"

    async def _get(
        self, endpoint: str, params: dict[str, Any]
    ) -> httpx.Response:
        """GET with bounded retries. Returns the final response or raises.

        Raises:
            _RetryableHttpError: retries exhausted on a transient failure.
        """
        await self._respect_known_rate_limit()
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=self._retry_wait_initial, max=10.0),
            retry=retry_if_exception_type(_RetryableHttpError),
            reraise=True,
        ):
            with attempt:
                try:
                    response = await self._get_client().get(endpoint, params=params)
                except httpx.TimeoutException as exc:
                    raise _RetryableHttpError(
                        f"GitHub request timed out: {type(exc).__name__}"
                    ) from exc
                except httpx.HTTPError as exc:
                    raise _RetryableHttpError(
                        f"GitHub network error: {type(exc).__name__}: {exc}"
                    ) from exc
                self._record_rate_limit_headers(response)
                action = self._classify_response(response)
                if action == "ok":
                    return response
                if action == "retry":
                    hint = _rate_limit_wait_seconds(response)
                    if hint > MAX_RATE_LIMIT_WAIT_SECONDS:
                        # Do not sleep past the cap: fail without retrying.
                        raise _NonRetryableWrapper(
                            _RetryableHttpError(
                                f"GitHub rate-limit wait ({hint:.0f}s) exceeds cap; "
                                f"status={response.status_code}",
                                status_code=response.status_code,
                                wait_hint=hint,
                            )
                        )
                    if hint > 0:
                        await self._sleep_fn(min(hint, MAX_RATE_LIMIT_WAIT_SECONDS))
                    raise _RetryableHttpError(
                        f"GitHub transient error {response.status_code}",
                        status_code=response.status_code,
                        wait_hint=hint,
                    )
                # Permanent failure: return it for the caller to record.
                return response
        raise _RetryableHttpError("GitHub request failed without a response")

    # -- search ----------------------------------------------------------

    async def search(
        self,
        queries: list[QueryVariant],
        max_results: int = 200,
    ) -> AdapterSearchResult:
        """Run query variants; return normalized discoveries + explicit errors."""
        discoveries: list[Discovery] = []
        errors: list[SearchError] = []
        for query in queries:
            if len(discoveries) >= max_results:
                break
            endpoint = _ENDPOINTS.get(query.search_type)
            if endpoint is None:
                errors.append(
                    SearchError(
                        source=f"github:{query.search_type}",
                        message=f"Unsupported search type: {query.search_type}",
                        retryable=False,
                    )
                )
                continue
            params: dict[str, Any] = {
                "q": build_q(query),
                "per_page": self._per_page,
                "page": 1,
            }
            try:
                response = await self._get(endpoint, params)
            except _NonRetryableWrapper as exc:
                inner = exc.inner
                errors.append(
                    SearchError(
                        source=f"github:{query.search_type}",
                        status_code=inner.status_code,
                        message=inner.message,
                        retryable=False,
                    )
                )
                continue
            except _RetryableHttpError as exc:
                errors.append(
                    SearchError(
                        source=f"github:{query.search_type}",
                        status_code=exc.status_code,
                        message=f"{exc.message} (retries exhausted)",
                        retryable=True,
                    )
                )
                continue
            if response.status_code != 200:
                errors.append(
                    SearchError(
                        source=f"github:{query.search_type}",
                        status_code=response.status_code,
                        message=self._describe_error(response),
                        retryable=False,
                    )
                )
                continue
            try:
                payload = response.json()
            except ValueError as exc:
                errors.append(
                    SearchError(
                        source=f"github:{query.search_type}",
                        status_code=response.status_code,
                        message=f"Malformed JSON in GitHub response: {exc}",
                        retryable=False,
                    )
                )
                continue
            items = payload.get("items", []) if isinstance(payload, dict) else []
            for item in items:
                if len(discoveries) >= max_results:
                    break
                if not isinstance(item, dict):
                    continue
                try:
                    discoveries.append(self._normalize_item(query, item))
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(
                        SearchError(
                            source=f"github:{query.search_type}",
                            status_code=200,
                            message=f"Skipping malformed result item: {exc}",
                            retryable=False,
                        )
                    )
        if discoveries:
            await self._enrich_readmes(discoveries, errors)
        return AdapterSearchResult(discoveries=discoveries, errors=errors)

    # -- normalization ----------------------------------------------------

    def _search_terms(self, query: QueryVariant) -> list[str]:
        # Candidate match terms: target aliases/intents plus the query's own
        # keyword text (the builder already folds user keywords into
        # query_text, so no separate keywords field is needed here).
        try:
            from raven_targeter.config.aliases import get_aliases

            aliases = get_aliases(query.target)
            return (
                list(aliases.names) + list(aliases.intents) + [query.query_text]
            )
        except ValueError:
            return [query.query_text]

    def _normalize_item(self, query: QueryVariant, item: dict[str, Any]) -> Discovery:
        if query.search_type == "repository":
            return self._normalize_repo(query, item)
        if query.search_type == "code":
            return self._normalize_code(query, item)
        return self._normalize_issue(query, item)

    def _matched_from_text(self, query: QueryVariant, *texts: Any) -> list[str]:
        haystack = "\n".join(str(t) for t in texts if t)
        return find_matched_terms(haystack, self._search_terms(query))

    def _normalize_repo(self, query: QueryVariant, item: dict[str, Any]) -> Discovery:
        owner = item["owner"]["login"]
        name = item["name"]
        full_name = item.get("full_name") or f"{owner}/{name}"
        url = item["html_url"]
        description = redact_text(str(item.get("description") or ""))[:DESCRIPTION_MAX_CHARS]
        return Discovery(
            source="github",
            source_type="repository",
            provider=query.target,
            title=full_name,
            url=url,
            author=str(owner),
            created_at=parse_github_timestamp(item.get("created_at")),
            updated_at=parse_github_timestamp(item.get("updated_at")),
            pushed_at=parse_github_timestamp(item.get("pushed_at")),
            description=description or None,
            stars=item.get("stargazers_count"),
            forks=item.get("forks_count"),
            matched_terms=self._matched_from_text(query, full_name, description),
            evidence=[f"Matched repository search: {query.query_text}"],
            canonical_url=canonicalize_url(url),
            repo_identity=canonical_repo_identity(owner, name),
        )

    def _normalize_code(self, query: QueryVariant, item: dict[str, Any]) -> Discovery:
        repo = item.get("repository") or {}
        owner = (repo.get("owner") or {}).get("login", "")
        repo_name = repo.get("name", "")
        url = item.get("html_url", "")
        path = item.get("path", "")
        title = f"{repo.get('full_name', '')} — {path}".strip(" —")
        return Discovery(
            source="github",
            source_type="code",
            provider=query.target,
            title=title or url,
            url=url,
            author=str(owner) or None,
            # Code search items carry no dates; the parent repository
            # (linked via repo_identity) provides recency evidence.
            description=None,
            stars=None,
            forks=None,
            matched_terms=self._matched_from_text(query, path, title),
            evidence=[f"Matched code search: {query.query_text}"],
            canonical_url=canonicalize_url(url) if url else "",
            repo_identity=(
                canonical_repo_identity(owner, repo_name) if owner and repo_name else None
            ),
        )

    def _normalize_issue(self, query: QueryVariant, item: dict[str, Any]) -> Discovery:
        is_pr = isinstance(item.get("pull_request"), dict)
        source_type = "pull_request" if is_pr else "issue"
        url = item.get("html_url", "")
        title = str(item.get("title", "") or url)
        body = redact_text(str(item.get("body") or ""))[:DESCRIPTION_MAX_CHARS]
        user = item.get("user") or {}
        repo_identity = self._repo_identity_from_api_url(
            str(item.get("repository_url") or "")
        )
        return Discovery(
            source="github",
            source_type=source_type,  # type: ignore[arg-type]
            provider=query.target,
            title=title,
            url=url,
            author=str(user.get("login")) if user.get("login") else None,
            created_at=parse_github_timestamp(item.get("created_at")),
            updated_at=parse_github_timestamp(item.get("updated_at")),
            pushed_at=None,
            description=body or None,
            stars=None,
            forks=None,
            matched_terms=self._matched_from_text(query, title, body),
            evidence=[f"Matched {source_type} search: {query.query_text}"],
            canonical_url=canonicalize_url(url) if url else "",
            repo_identity=repo_identity,
        )

    @staticmethod
    def _repo_identity_from_api_url(api_url: str) -> str | None:
        """Turn https://api.github.com/repos/owner/repo into an identity."""
        prefix = "https://api.github.com/repos/"
        if not api_url.startswith(prefix):
            return None
        parts = api_url[len(prefix):].strip("/").split("/")
        if len(parts) >= 2:
            return canonical_repo_identity(parts[0], parts[1])
        return None

    # -- README enrichment --------------------------------------------------

    async def _enrich_readmes(
        self, discoveries: list[Discovery], errors: list[SearchError]
    ) -> None:
        """Fetch raw READMEs for the first N repository discoveries.

        Failures are non-fatal: they append an error and leave the
        discovery in place without README evidence.
        """
        enriched = 0
        for index, discovery in enumerate(discoveries):
            if enriched >= self._max_readme_enrich:
                break
            if discovery.source_type != "repository" or not discovery.repo_identity:
                continue
            # repo_identity is "github.com/owner/repo".
            parts = discovery.repo_identity.split("/")
            if len(parts) != 3:
                continue
            _, owner, repo = parts
            endpoint = f"/repos/{owner}/{repo}/readme"
            try:
                response = await self._get_client().get(
                    endpoint,
                    headers={"Accept": "application/vnd.github.raw"},
                )
            except httpx.HTTPError as exc:
                errors.append(
                    SearchError(
                        source="github:readme",
                        message=f"README fetch failed for {owner}/{repo}: "
                        f"{type(exc).__name__}",
                        retryable=True,
                    )
                )
                continue
            self._record_rate_limit_headers(response)
            if response.status_code != 200:
                errors.append(
                    SearchError(
                        source="github:readme",
                        status_code=response.status_code,
                        message=f"README fetch failed for {owner}/{repo}: "
                        f"HTTP {response.status_code}",
                        retryable=response.status_code
                        in (429, 500, 502, 503, 504),
                    )
                )
                continue
            excerpt = redact_text(response.text)[:README_MAX_CHARS]
            if excerpt.strip():
                discoveries[index] = discovery.model_copy(
                    update={
                        "evidence": [
                            *discovery.evidence,
                            f"README excerpt: {excerpt}",
                        ]
                    }
                )
            enriched += 1
