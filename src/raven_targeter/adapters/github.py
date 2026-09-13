"""GitHub REST discovery adapter with endpoint enrichment, leak detection,
and optional credential verification."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

from raven_targeter.config.aliases import get_aliases
from raven_targeter.config.settings import Settings
from raven_targeter.core.endpoint_extractor import extract_candidate_endpoints
from raven_targeter.core.leak_detector import detect_leaks_raw, high_confidence_findings
from raven_targeter.core.sanitizer import find_matched_terms, redact_text
from raven_targeter.models import (
    AdapterSearchResult,
    Discovery,
    LeakAlert,
    QueryVariant,
    SearchError,
    VerifyOutcome,
)
from raven_targeter.utils.dates import parse_github_timestamp
from raven_targeter.utils.urls import canonical_repo_identity, canonicalize_url

logger = logging.getLogger(__name__)
API_BASE = "https://api.github.com"
ENDPOINTS = {
    "repository": "/search/repositories",
    "code": "/search/code",
    "issue": "/search/issues",
    "pull_request": "/search/issues",
}
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RATE_WAIT = 60.0

VerifyCallback = Callable[[str, str], Awaitable[VerifyOutcome]]


def build_q(q: QueryVariant) -> str:
    parts = [q.query_text]
    qualifiers = dict(q.qualifiers)
    if q.search_type == "issue":
        qualifiers.setdefault("type", "issue")
    if q.search_type == "pull_request":
        qualifiers.setdefault("type", "pr")
    for key, value in sorted(qualifiers.items()):
        parts.append(f"{key}:{value}")
    return " ".join(parts)


class GitHubAdapter:
    name = "github"

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = 15.0,
        per_page: int = 30,
        max_attempts: int = 3,
        max_enrich_per_group: int = 20,
        transport: httpx.AsyncBaseTransport | None = None,
        verify_callback: VerifyCallback | None = None,
    ) -> None:
        self.token = token.strip() if token else None
        self.timeout = timeout
        self.per_page = min(max(per_page, 1), 100)
        self.max_attempts = max_attempts
        self.max_enrich = max_enrich_per_group
        self.transport = transport
        self.verify_callback = verify_callback
        self._client: httpx.AsyncClient | None = None
        self.rate_buckets: dict[str, tuple[int | None, float | None]] = {}

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> GitHubAdapter:
        return cls(settings.github_token, **kwargs)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": "Raven-Targeter/0.3",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.AsyncClient(
                base_url=API_BASE, headers=headers, timeout=self.timeout, transport=self.transport
            )
        return self._client

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _record_rate(self, response: httpx.Response) -> None:
        resource = response.headers.get("x-ratelimit-resource", "unknown")
        try:
            remaining = int(response.headers["x-ratelimit-remaining"])
        except (KeyError, ValueError):
            remaining = None
        try:
            reset = float(response.headers["x-ratelimit-reset"])
        except (KeyError, ValueError):
            reset = None
        self.rate_buckets[resource] = (remaining, reset)

    async def _request(self, path: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                response = await self._get_client().get(path, params=params, headers=headers)
                self._record_rate(response)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt + 1 >= self.max_attempts:
                    raise
                await asyncio.sleep(min(2**attempt, 5))
                continue
            if response.status_code not in RETRY_STATUSES and not (
                response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"
            ):
                return response
            if attempt + 1 >= self.max_attempts:
                return response
            retry_after = response.headers.get("retry-after")
            wait = 0.0
            if retry_after:
                try:
                    wait = float(retry_after)
                except ValueError:
                    wait = 0.0
            elif response.headers.get("x-ratelimit-remaining") == "0":
                try:
                    wait = max(0.0, float(response.headers["x-ratelimit-reset"]) - time.time() + 1)
                except (KeyError, ValueError):
                    wait = 0.0
            if wait > MAX_RATE_WAIT:
                return response
            await asyncio.sleep(wait or min(2**attempt, 5))
        if last:
            raise last
        raise RuntimeError("request exhausted without response")

    async def search(self, queries: list[QueryVariant], max_results: int = 200) -> AdapterSearchResult:
        discoveries: list[Discovery] = []
        errors: list[SearchError] = []
        leak_alerts: list[LeakAlert] = []
        for q in queries:
            if len(discoveries) >= max_results:
                break
            endpoint = ENDPOINTS[q.search_type]
            try:
                response = await self._request(endpoint, params={
                    "q": build_q(q), "per_page": self.per_page, "page": 1
                })
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                errors.append(SearchError(source=f"github:{q.search_type}", message=str(exc), retryable=True))
                continue
            if response.status_code != 200:
                errors.append(SearchError(
                    source=f"github:{q.search_type}", status_code=response.status_code,
                    message=self._error_message(response), retryable=response.status_code in RETRY_STATUSES,
                ))
                continue
            try:
                payload = response.json()
            except ValueError as exc:
                errors.append(SearchError(source=f"github:{q.search_type}", status_code=200, message=f"Malformed JSON: {exc}"))
                continue
            for item in payload.get("items", []) if isinstance(payload, dict) else []:
                if len(discoveries) >= max_results:
                    break
                if not isinstance(item, dict):
                    continue
                try:
                    discoveries.append(self._normalize(q, item))
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(SearchError(source=f"github:{q.search_type}", message=f"Malformed item: {exc}"))
        if discoveries and queries:
            kind = queries[0].search_type
            if kind == "repository":
                await self._enrich_readmes(discoveries, errors, leak_alerts)
            elif kind == "code":
                await self._enrich_code(discoveries, errors, leak_alerts)
        return AdapterSearchResult(discoveries=discoveries, errors=errors, leak_alerts=leak_alerts)

    def _terms(self, q: QueryVariant) -> list[str]:
        aliases = get_aliases(q.target)
        return [*aliases.names, *aliases.intents]

    def _normalize(self, q: QueryVariant, item: dict[str, Any]) -> Discovery:
        if q.search_type == "repository":
            owner = item["owner"]["login"]
            name = item["name"]
            desc = redact_text(str(item.get("description") or ""))[:1500]
            url = str(item["html_url"])
            return Discovery(
                source_type="repository", provider=q.target, title=item.get("full_name") or f"{owner}/{name}",
                url=url, canonical_url=canonicalize_url(url), author=owner,
                created_at=parse_github_timestamp(item.get("created_at")),
                updated_at=parse_github_timestamp(item.get("updated_at")),
                pushed_at=parse_github_timestamp(item.get("pushed_at")),
                description=desc or None, stars=item.get("stargazers_count"), forks=item.get("forks_count"),
                matched_terms=find_matched_terms(f"{owner}/{name}\n{desc}", self._terms(q)),
                evidence=[f"Matched repository search ({q.freshness_axis}): {q.query_text}"],
                repo_identity=canonical_repo_identity(owner, name),
            )
        if q.search_type == "code":
            repo = item.get("repository") or {}
            owner = (repo.get("owner") or {}).get("login")
            name = repo.get("name")
            path = str(item.get("path") or "")
            url = str(item.get("html_url") or "")
            return Discovery(
                source_type="code", provider=q.target,
                title=f"{repo.get('full_name','')} — {path}".strip(" —"), url=url,
                canonical_url=canonicalize_url(url), author=owner, source_path=path,
                matched_terms=find_matched_terms(path, self._terms(q)),
                evidence=[f"Matched code search: {q.query_text}"],
                repo_identity=canonical_repo_identity(owner, name) if owner and name else None,
            )
        is_pr = q.search_type == "pull_request" or isinstance(item.get("pull_request"), dict)
        user = item.get("user") or {}
        url = str(item.get("html_url") or "")
        body = redact_text(str(item.get("body") or ""))[:1500]
        repo_identity = self._repo_identity_from_api_url(str(item.get("repository_url") or ""))
        return Discovery(
            source_type="pull_request" if is_pr else "issue", provider=q.target,
            title=str(item.get("title") or url), url=url, canonical_url=canonicalize_url(url),
            author=user.get("login"), created_at=parse_github_timestamp(item.get("created_at")),
            updated_at=parse_github_timestamp(item.get("updated_at")), description=body or None,
            matched_terms=find_matched_terms(f"{item.get('title','')}\n{body}", self._terms(q)),
            evidence=[f"Matched {'PR' if is_pr else 'issue'} search ({q.freshness_axis})"],
            repo_identity=repo_identity,
        )

    @staticmethod
    def _repo_identity_from_api_url(url: str) -> str | None:
        marker = "/repos/"
        if marker not in url:
            return None
        parts = url.split(marker, 1)[1].strip("/").split("/")
        return canonical_repo_identity(parts[0], parts[1]) if len(parts) >= 2 else None

    async def _enrich_readmes(
        self, discoveries: list[Discovery], errors: list[SearchError], leak_alerts: list[LeakAlert]
    ) -> None:
        count = 0
        for i, d in enumerate(discoveries):
            if count >= self.max_enrich or d.source_type != "repository" or not d.repo_identity:
                continue
            _, owner, repo = d.repo_identity.split("/", 2)
            try:
                response = await self._request(f"/repos/{owner}/{repo}/readme", headers={"Accept": "application/vnd.github.raw"})
            except httpx.HTTPError as exc:
                errors.append(SearchError(source="github:readme", message=str(exc), retryable=True))
                continue
            if response.status_code != 200:
                continue
            raw_text = response.text[:15000]
            leak_alerts.extend(
                await self._build_leak_alerts(raw_text, discovery=d, source_file="README")
            )
            text = redact_text(raw_text)
            endpoints = extract_candidate_endpoints(text, source_file="README")
            discoveries[i] = d.model_copy(update={
                "evidence": [*d.evidence, f"README excerpt: {text[:2500]}"],
                "candidate_endpoints": endpoints,
            })
            count += 1

    async def _enrich_code(
        self, discoveries: list[Discovery], errors: list[SearchError], leak_alerts: list[LeakAlert]
    ) -> None:
        count = 0
        for i, d in enumerate(discoveries):
            if count >= self.max_enrich or d.source_type != "code" or not d.repo_identity or not d.source_path:
                continue
            _, owner, repo = d.repo_identity.split("/", 2)
            try:
                response = await self._request(
                    f"/repos/{owner}/{repo}/contents/{d.source_path}",
                    headers={"Accept": "application/vnd.github.raw"},
                )
            except httpx.HTTPError as exc:
                errors.append(SearchError(source="github:code-content", message=str(exc), retryable=True))
                continue
            if response.status_code != 200:
                continue
            raw_text = response.text[:12000]
            leak_alerts.extend(
                await self._build_leak_alerts(raw_text, discovery=d, source_file=d.source_path)
            )
            text = redact_text(raw_text)
            endpoints = extract_candidate_endpoints(text, source_file=d.source_path)
            discoveries[i] = d.model_copy(update={
                "evidence": [*d.evidence, f"Code excerpt ({d.source_path}): {text[:2000]}"],
                "candidate_endpoints": endpoints,
            })
            count += 1

    async def _build_leak_alerts(
        self, raw_text: str, *, discovery: Discovery, source_file: str | None
    ) -> list[LeakAlert]:
        """Run leak detection on raw text; optionally verify high-confidence hits.

        Uses detect_leaks_raw so the raw secret is available for the verifier
        callback — it is never stored on the LeakAlert, logged, or exported.
        """
        alerts: list[LeakAlert] = []
        for finding, raw_secret in detect_leaks_raw(raw_text, source_file=source_file):
            if finding.suppressed_reason is not None:
                continue
            if finding.confidence < 0.6:
                continue

            alert = LeakAlert(
                discovery_id=discovery.id,
                repo_identity=discovery.repo_identity,
                repo_url=discovery.url,
                source_file=finding.source_file,
                line_number=finding.line_number,
                pattern_name=finding.pattern_name,
                confidence=finding.confidence,
                entropy=finding.entropy,
                redacted_preview=finding.redacted_preview,
                context_line_redacted=finding.context_line_redacted,
            )

            if self.verify_callback is not None:
                try:
                    outcome = await self.verify_callback(finding.pattern_name, raw_secret)
                    alert = alert.model_copy(update={"verification": outcome})
                except Exception:  # noqa: BLE001 - verification failure must not abort the scan
                    pass

            alerts.append(alert)
        return alerts

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("message"):
                return str(body["message"])[:500]
        except ValueError:
            pass
        return f"GitHub API HTTP {response.status_code}"