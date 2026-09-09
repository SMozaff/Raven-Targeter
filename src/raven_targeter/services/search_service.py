"""End-to-end search orchestration: pipeline plus Qt worker thread.

Two layers:

- :class:`SearchPipeline` — GUI-independent async orchestration. Takes a
  search request, runs query building, adapter search per source group,
  classification, scoring, date validation, deduplication, and
  persistence. Fully testable without Qt.
- :class:`SearchWorker` — a ``QObject`` that runs the pipeline on a
  ``QThread`` and reports through signals, so the GUI never freezes.
  Discoveries stream progressively via :attr:`discovery_found`; the
  final deduplicated list arrives with :attr:`finished`.

Cancellation is cooperative: the worker's cancel flag is checked between
pipeline stages (never mid-HTTP-request). A cancelled run is still
closed out in the database with status ``"cancelled"``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal, Slot

from raven_targeter.adapters.base import AdapterSearchResult, SearchAdapter, SearchError
from raven_targeter.adapters.github import GitHubAdapter
from raven_targeter.config.settings import Settings
from raven_targeter.core.date_validator import classify_repo_dates
from raven_targeter.core.deduplicator import deduplicate
from raven_targeter.core.query_builder import build_queries
from raven_targeter.core.sanitizer import detect_api_patterns
from raven_targeter.core.scorer import classify_evidence, score_discovery
from raven_targeter.database.repository import RavenRepository
from raven_targeter.models import Discovery, QueryVariant, SearchRequest

logger = logging.getLogger(__name__)

GROUP_ORDER = ("repository", "code", "issue", "pull_request")

GROUP_LABELS = {
    "repository": "Searching repositories",
    "code": "Searching code",
    "issue": "Searching issues",
    "pull_request": "Searching pull requests",
}


@dataclass(frozen=True)
class PipelineResult:
    """Outcome of one pipeline run (also mirrored into the database)."""

    run_id: str
    accepted: list[Discovery] = field(default_factory=list)
    errors: list[SearchError] = field(default_factory=list)
    candidate_count: int = 0
    status: str = "completed"

    @property
    def accepted_count(self) -> int:
        """Number of final discoveries."""
        return len(self.accepted)


class PipelineFailedError(Exception):
    """An unexpected failure converted with context (run is marked failed)."""

    def __init__(self, run_id: str, message: str) -> None:
        super().__init__(message)
        self.run_id = run_id


class _Cancelled(Exception):
    """Internal: cooperative cancellation between pipeline stages."""


class SearchPipeline:
    """Async search pipeline. No Qt dependency — safe to unit test."""

    def __init__(
        self,
        *,
        progress_cb: Callable[[str, int], None] | None = None,
        discovery_cb: Callable[[Discovery], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        self._progress_cb = progress_cb or (lambda _msg, _pct: None)
        self._discovery_cb = discovery_cb or (lambda _d: None)
        self._should_cancel = should_cancel or (lambda: False)

    def _progress(self, message: str, percent: int) -> None:
        logger.info("Search progress: %s (%d%%)", message, percent)
        self._progress_cb(message, percent)

    def _check_cancel(self) -> None:
        if self._should_cancel():
            raise _Cancelled()

    async def run(
        self,
        request: SearchRequest,
        adapter: SearchAdapter,
        repository: RavenRepository,
    ) -> PipelineResult:
        """Execute the full pipeline for one request.

        Raises:
            _Cancelled: cooperative cancellation (worker converts to signal).
            PipelineFailedError: unexpected failure, run marked failed.
        """
        self._progress("Generating queries", 5)
        self._check_cancel()
        queries = build_queries(request)

        run_id = repository.create_run(
            request.lookback_days, request.targets, request.sources
        )
        try:
            return await self._execute(request, queries, run_id, adapter, repository)
        except _Cancelled:
            self._close_run(repository, run_id, [], [], 0, "cancelled")
            raise
        except PipelineFailedError:
            raise
        except Exception as exc:
            # Convert with context: mark the run failed, then re-raise typed.
            try:
                self._close_run(
                    repository,
                    run_id,
                    [],
                    [
                        SearchError(
                            source="pipeline",
                            message=f"Unexpected pipeline failure: {exc}",
                            retryable=False,
                        )
                    ],
                    0,
                    "failed",
                )
            except Exception as close_exc:
                logger.error(
                    "Failed to close run %s as failed: %s", run_id, close_exc
                )
            raise PipelineFailedError(
                run_id, f"Search pipeline failed: {exc}"
            ) from exc

    async def _execute(
        self,
        request: SearchRequest,
        queries: list[QueryVariant],
        run_id: str,
        adapter: SearchAdapter,
        repository: RavenRepository,
    ) -> PipelineResult:
        groups: dict[str, list] = {kind: [] for kind in GROUP_ORDER}
        for query in queries:
            if query.search_type in groups:
                groups[query.search_type].append(query)
        active_groups = [kind for kind in GROUP_ORDER if groups[kind]]

        all_hits: list[Discovery] = []
        all_errors: list[SearchError] = []
        for position, kind in enumerate(active_groups):
            self._check_cancel()
            # Spread group searches across 10-70% of the progress bar.
            percent = 10 + int(60 * position / max(1, len(active_groups)))
            self._progress(GROUP_LABELS[kind], percent)
            group_result: AdapterSearchResult = await adapter.search(
                groups[kind], max_results=request.max_results_per_source
            )
            all_hits.extend(group_result.discoveries)
            all_errors.extend(group_result.errors)
            if kind == "repository":
                # README enrichment happens inside the adapter's search
                # call, which has just completed for repositories.
                self._progress("Inspecting README files", percent + 2)

        self._check_cancel()
        self._progress("Scoring", 80)
        accepted = self._analyze(request, all_hits)
        for discovery in accepted:
            self._discovery_cb(discovery)

        self._check_cancel()
        self._progress("Saving", 90)
        self._close_run(
            repository, run_id, accepted, all_errors, len(all_hits), "completed"
        )

        self._progress("Complete", 100)
        return PipelineResult(
            run_id=run_id,
            accepted=accepted,
            errors=all_errors,
            candidate_count=len(all_hits),
            status="completed",
        )

    def _analyze(
        self, request: SearchRequest, hits: list[Discovery]
    ) -> list[Discovery]:
        """Classify, score, date-filter, deduplicate, and apply min score."""
        scored: list[Discovery] = []
        for hit in hits:
            combined_text = "\n".join(
                [hit.title, hit.description or "", *hit.evidence]
            )
            classification = classify_evidence(combined_text, hit.source_type)
            classified = hit.model_copy(update={"classification": classification})
            patterns = detect_api_patterns(combined_text)
            breakdown = score_discovery(
                classified, request.lookback_days, api_patterns=patterns
            )
            scored.append(
                classified.model_copy(
                    update={
                        "relevance_score": breakdown.relevance,
                        "freshness_score": breakdown.freshness,
                        "implementation_score": breakdown.implementation_evidence,
                        "engagement_score": breakdown.engagement,
                        "confidence_score": breakdown.confidence,
                    }
                )
            )

        # Date validation: repository/issue/PR hits must be recent. Code
        # hits carry no dates of their own — they survive only when their
        # parent repository qualified (implementation evidence for an
        # accepted repo).
        dated = [d for d in scored if d.source_type != "code"]
        code_hits = [d for d in scored if d.source_type == "code"]
        accepted_identities: set[str] = set()
        recent: list[Discovery] = []
        for discovery in dated:
            status = classify_repo_dates(
                discovery.created_at,
                discovery.pushed_at,
                request.lookback_days,
                updated_at=discovery.updated_at,
            )
            if status.is_recent:
                recent.append(discovery)
                if discovery.repo_identity:
                    accepted_identities.add(discovery.repo_identity)
        for discovery in code_hits:
            if (
                discovery.repo_identity
                and discovery.repo_identity in accepted_identities
            ):
                recent.append(discovery)

        merged, _removed = deduplicate(recent)
        return [
            d for d in merged if d.total_score >= request.minimum_score
        ]

    @staticmethod
    def _close_run(
        repository: RavenRepository,
        run_id: str,
        accepted: list[Discovery],
        errors: list[SearchError],
        candidate_count: int,
        status: str,
    ) -> None:
        repository.save_discoveries(run_id, accepted)
        repository.save_errors(run_id, errors)
        repository.complete_run(
            run_id,
            candidate_count=candidate_count,
            accepted_count=len(accepted),
            error_count=len(errors),
            status=status,
        )


class SearchWorker(QObject):
    """Runs :class:`SearchPipeline` on a worker thread via Qt signals."""

    progress_message = Signal(str)
    progress_percent = Signal(int)
    discovery_found = Signal(object)
    finished = Signal(str)
    failed = Signal(str)
    search_cancelled = Signal()

    def __init__(
        self,
        settings: Settings,
        repository: RavenRepository,
        adapter_factory: Callable[[], GitHubAdapter] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._repository = repository
        self._adapter_factory = (
            adapter_factory or (lambda: GitHubAdapter.from_settings(settings))
        )
        self._cancel_event = threading.Event()

    @Slot(object)
    def run(self, request: SearchRequest) -> None:
        """Execute the pipeline. Invoked in the worker thread."""
        self._cancel_event.clear()

        def on_progress(message: str, percent: int) -> None:
            self.progress_message.emit(message)
            self.progress_percent.emit(percent)

        pipeline = SearchPipeline(
            progress_cb=on_progress,
            discovery_cb=self.discovery_found.emit,
            should_cancel=self._cancel_event.is_set,
        )
        try:
            result = asyncio.run(self._execute(request, pipeline))
        except _Cancelled:
            logger.info("Search cancelled by user")
            self.search_cancelled.emit()
        except PipelineFailedError as exc:
            logger.error("Search failed: %s", exc)
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result.run_id)

    async def _execute(
        self, request: SearchRequest, pipeline: SearchPipeline
    ) -> PipelineResult:
        adapter = self._adapter_factory()
        try:
            return await pipeline.run(request, adapter, self._repository)
        finally:
            await adapter.aclose()

    def cancel(self) -> None:
        """Request cooperative cancellation. Thread-safe; returns at once."""
        self._cancel_event.set()
