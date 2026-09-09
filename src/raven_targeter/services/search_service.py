"""End-to-end GitHub + optional web-search discovery pipeline."""
from __future__ import annotations

from collections import defaultdict
from typing import Protocol

from raven_targeter.adapters.base import SearchAdapter
from raven_targeter.core.date_validator import classify_dates
from raven_targeter.core.deduplicator import deduplicate
from raven_targeter.core.query_builder import build_queries
from raven_targeter.core.scorer import score
from raven_targeter.models import AdapterSearchResult, Discovery, SearchError, SearchRequest


class WebSearchAdapter(Protocol):
    async def search_targets(
        self,
        targets: list[str],
        keywords: list[str],
        *,
        lookback_days: int,
        max_results: int,
    ) -> AdapterSearchResult: ...

    async def aclose(self) -> None: ...


class SearchPipeline:
    async def run(
        self,
        request: SearchRequest,
        adapter: SearchAdapter | None = None,
        web_adapter: WebSearchAdapter | None = None,
    ) -> tuple[list[Discovery], list[SearchError]]:
        hits: list[Discovery] = []
        errors: list[SearchError] = []

        if adapter is not None:
            queries = build_queries(request)
            by_kind: dict[str, list] = defaultdict(list)
            for q in queries:
                by_kind[q.search_type].append(q)

            for kind in ("repository", "code", "issue", "pull_request"):
                group = by_kind.get(kind, [])
                if not group:
                    continue
                result: AdapterSearchResult = await adapter.search(
                    group, max_results=request.max_raw_candidates_per_source
                )
                hits.extend(result.discoveries)
                errors.extend(result.errors)

        if request.web_search:
            if web_adapter is None:
                errors.append(
                    SearchError(
                        source="web_search",
                        message="Web Search selected but no configured Search API adapter is available",
                        retryable=False,
                    )
                )
            else:
                web_result = await web_adapter.search_targets(
                    request.targets,
                    request.keywords,
                    lookback_days=request.lookback_days,
                    max_results=request.max_raw_candidates_per_source,
                )
                hits.extend(web_result.discoveries)
                errors.extend(web_result.errors)

        # First establish which GitHub repositories satisfy the time window.
        recent_repo_ids: set[str] = set()
        eligible: list[Discovery] = []
        for d in hits:
            if d.source_type == "repository":
                if classify_dates(
                    d.created_at, d.pushed_at, d.updated_at, request.lookback_days
                ).is_recent:
                    eligible.append(d)
                    if d.repo_identity:
                        recent_repo_ids.add(d.repo_identity)
            elif d.source_type in {"issue", "pull_request"}:
                if classify_dates(
                    d.created_at, None, d.updated_at, request.lookback_days
                ).is_recent:
                    eligible.append(d)
            elif d.source_type == "web":
                # Web results are accepted from the configured provider. The
                # scorer distinguishes explicit server-side recency filtering
                # from unknown publication dates.
                eligible.append(d)

        # GitHub code hits have no usable search date; only keep them when
        # their parent repository independently qualifies as recent.
        eligible.extend(
            d
            for d in hits
            if d.source_type == "code"
            and d.repo_identity
            and d.repo_identity in recent_repo_ids
        )

        scored = [score(d, request.lookback_days) for d in eligible]
        merged, _ = deduplicate(scored)
        final = [d for d in merged if d.total_score >= request.minimum_score]
        final.sort(key=lambda d: (-d.total_score, d.provider or "", d.title.lower()))
        return final[: request.max_results_per_source], errors
