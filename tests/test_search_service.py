"""Tests for the M5 end-to-end pipeline and worker thread.

The pipeline is exercised directly (no Qt) with a fake adapter, plus two
threaded integration tests (offscreen) proving GUI-thread safety:
worker signals stream out of a real QThread, and MainWindow wires a full
request → results → dashboard cycle without touching the network.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QApplication

from raven_targeter.adapters.base import (
    AdapterSearchResult,
    SearchAdapter,
    SearchError,
)
from raven_targeter.config.settings import Settings
from raven_targeter.database.database import build_engine, init_db
from raven_targeter.database.repository import RavenRepository
from raven_targeter.gui.main_window import MainWindow
from raven_targeter.models import Discovery, QueryVariant, SearchRequest
from raven_targeter.services.search_service import (
    PipelineFailedError,
    SearchPipeline,
    SearchWorker,
    _Cancelled,
)


def _ref() -> datetime:
    return datetime.now(UTC)


def _repo(url: str, days_old: float = 1.0, **overrides) -> Discovery:
    ref = _ref()
    data = {
        "title": f"Claude API proxy {url}",
        "url": url,
        "source_type": "repository",
        "provider": "openai",
        "author": "someone",
        "created_at": ref - timedelta(days=days_old),
        "pushed_at": ref - timedelta(hours=2),
        "description": "An unofficial Claude API proxy server",
        "stars": 12,
        "forks": 3,
        "matched_terms": ["Claude", "proxy"],
        "evidence": ["Matched repository search"],
        "classification": "unknown",
        "canonical_url": url,
        "repo_identity": "github.com/someone/proxy",
    }
    data.update(overrides)
    return Discovery(**data)


class FakeAdapter(SearchAdapter):
    """Canned per-source-group hits; records queries; optional failure."""

    name = "fake"

    def __init__(
        self,
        by_group: dict[str, list[Discovery]] | None = None,
        errors: list[SearchError] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self.by_group = by_group or {}
        self.errors = errors or []
        self.fail_with = fail_with
        self.seen_queries: list[QueryVariant] = []
        self.closed = False

    async def search(
        self, queries: list[QueryVariant], max_results: int = 200
    ) -> AdapterSearchResult:
        if self.fail_with is not None:
            raise self.fail_with
        self.seen_queries.extend(queries)
        kind = queries[0].search_type if queries else "repository"
        return AdapterSearchResult(
            discoveries=list(self.by_group.get(kind, [])[:max_results]),
            errors=list(self.errors),
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def repository(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path}/m5.db")
    init_db(engine)
    repository = RavenRepository(engine)
    yield repository
    engine.dispose()


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _request(**overrides) -> SearchRequest:
    data = {
        "targets": ["openai"],
        "lookback_days": 10,
        "sources": ["repository", "code", "issue", "pull_request"],
        "max_results_per_source": 50,
        "minimum_score": 0.0,
    }
    data.update(overrides)
    return SearchRequest(**data)


# -- pipeline ---------------------------------------------------------------


async def test_pipeline_full_run_scores_filters_dedups_persists(repository):
    repo_hit = _repo("https://github.com/someone/proxy")
    duplicate = _repo(
        "https://github.com/Someone/Proxy/",
        matched_terms=["wrapper"],
        evidence=["Matched code search"],
    )
    issue = _repo(
        "https://github.com/someone/proxy/issues/1",
        source_type="issue",
        title="Proxy auth discussion",
        description="How does the unofficial proxy handle keys?",
        repo_identity="github.com/someone/proxy",
        canonical_url="https://github.com/someone/proxy/issues/1",
    )
    code_child = _repo(
        "https://github.com/someone/proxy/blob/main/app.py",
        source_type="code",
        title="proxy app",
        description=None,
        created_at=None,
        pushed_at=None,
        updated_at=None,
        repo_identity="github.com/someone/proxy",
        canonical_url="https://github.com/someone/proxy/blob/main/app.py",
        matched_terms=["proxy"],
    )
    orphan_code = _repo(
        "https://github.com/other/old/blob/main/x.py",
        source_type="code",
        created_at=None,
        pushed_at=None,
        updated_at=None,
        repo_identity="github.com/other/old",
        canonical_url="https://github.com/other/old/blob/main/x.py",
    )
    stale = _repo(
        "https://github.com/someone/ancient",
        days_old=400.0,
        pushed_at=_ref() - timedelta(days=400),
        canonical_url="https://github.com/someone/ancient",
        repo_identity="github.com/someone/ancient",
    )
    adapter = FakeAdapter(
        by_group={
            "repository": [repo_hit, duplicate, stale],
            "code": [code_child, orphan_code],
            "issue": [issue],
            "pull_request": [],
        }
    )
    stages: list[str] = []
    streamed: list[Discovery] = []
    pipeline = SearchPipeline(
        progress_cb=lambda msg, _pct: stages.append(msg),
        discovery_cb=streamed.append,
    )

    result = await pipeline.run(_request(), adapter, repository)

    urls = {d.url for d in result.accepted}
    assert "https://github.com/someone/proxy" in urls  # merged duplicate
    assert "https://github.com/someone/proxy/issues/1" in urls
    assert "https://github.com/someone/proxy/blob/main/app.py" in urls  # child kept
    assert "https://github.com/other/old/blob/main/x.py" not in urls  # orphan dropped
    assert "https://github.com/someone/ancient" not in urls  # stale dropped
    assert len(result.accepted) == 3
    assert result.candidate_count == 6
    assert result.status == "completed"

    merged_repo = next(
        d for d in result.accepted if d.source_type == "repository"
    )
    assert merged_repo.classification == "proxy"
    assert set(merged_repo.matched_terms) >= {"Claude", "proxy", "wrapper"}
    assert merged_repo.total_score > 0

    for expected in (
        "Generating queries",
        "Searching repositories",
        "Inspecting README files",
        "Scoring",
        "Saving",
        "Complete",
    ):
        assert expected in stages
    assert {d.id for d in streamed} == {d.id for d in result.accepted}

    summary = repository.get_run(result.run_id)
    assert summary is not None
    assert summary.status == "completed"
    assert summary.candidate_count == 6
    assert summary.accepted_count == 3
    assert len(repository.get_discoveries(result.run_id)) == 3
    assert adapter.closed is False  # pipeline does not own the adapter


async def test_pipeline_min_score_filters(repository):
    adapter = FakeAdapter(by_group={"repository": [_repo("https://github.com/o/r")]})
    pipeline = SearchPipeline()
    result = await pipeline.run(_request(minimum_score=99.0), adapter, repository)
    assert result.accepted == []
    assert result.candidate_count == 1
    summary = repository.get_run(result.run_id)
    assert summary is not None and summary.accepted_count == 0


async def test_pipeline_adapter_errors_persisted(repository):
    adapter = FakeAdapter(
        by_group={"repository": [_repo("https://github.com/o/r")]},
        errors=[
            SearchError(
                source="github:code", status_code=429,
                message="Too Many Requests", retryable=True,
            )
        ],
    )
    pipeline = SearchPipeline()
    result = await pipeline.run(_request(), adapter, repository)
    assert len(result.errors) == 4  # one per searched group
    stored = repository.get_errors(result.run_id)
    assert len(stored) == 4
    assert stored[0].status_code == 429
    summary = repository.get_run(result.run_id)
    assert summary is not None and summary.error_count == 4


async def test_pipeline_cancel_before_adapter_creates_no_run(repository):
    adapter = FakeAdapter(by_group={"repository": [_repo("https://github.com/o/r")]})
    pipeline = SearchPipeline(should_cancel=lambda: True)
    with pytest.raises(_Cancelled):
        await pipeline.run(_request(), adapter, repository)
    assert adapter.seen_queries == []
    assert repository.list_runs() == []


async def test_pipeline_cancel_mid_run_marks_cancelled(repository):
    calls = {"n": 0}

    def cancel_after_three() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    adapter = FakeAdapter(by_group={"repository": [_repo("https://github.com/o/r")]})
    pipeline = SearchPipeline(should_cancel=cancel_after_three)
    with pytest.raises(_Cancelled):
        await pipeline.run(_request(), adapter, repository)
    runs = repository.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "cancelled"


async def test_pipeline_unexpected_error_marks_run_failed(repository):
    adapter = FakeAdapter(fail_with=RuntimeError("boom"))
    pipeline = SearchPipeline()
    with pytest.raises(PipelineFailedError):
        await pipeline.run(_request(), adapter, repository)
    runs = repository.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    stored = repository.get_errors(runs[0].id)
    assert any(e.source == "pipeline" for e in stored)


async def test_pipeline_builds_queries_for_all_targets(repository):
    adapter = FakeAdapter()
    pipeline = SearchPipeline()
    result = await pipeline.run(_request(targets=["openai", "grok"]), adapter, repository)
    seen_targets = {q.target for q in adapter.seen_queries}
    assert seen_targets == {"openai", "grok"}
    assert result.status == "completed"


# -- threaded worker ----------------------------------------------------------


def test_worker_threaded_run_streams_and_finishes(qapp, tmp_path):
    from PySide6.QtCore import QEventLoop

    engine = build_engine(f"sqlite:///{tmp_path}/worker.db")
    init_db(engine)
    repository = RavenRepository(engine)
    hit = _repo("https://github.com/o/r")
    made: dict[str, FakeAdapter] = {}

    def factory():
        made["adapter"] = FakeAdapter(by_group={"repository": [hit]})
        return made["adapter"]

    settings = Settings(_env_file=None)
    worker = SearchWorker(settings, repository, factory)
    thread = QThread()
    worker.moveToThread(thread)

    found: list[Discovery] = []
    finished: list[str] = []
    messages: list[str] = []
    worker.discovery_found.connect(found.append)
    worker.finished.connect(finished.append)
    worker.progress_message.connect(messages.append)

    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.failed.connect(loop.quit)
    QTimer.singleShot(15000, loop.quit)
    thread.started.connect(lambda: worker.run(_request(sources=["repository"])))
    thread.start()
    loop.exec()
    thread.quit()
    thread.wait(5000)

    try:
        assert len(finished) == 1
        assert len(found) == 1
        assert found[0].classification == "proxy"
        assert "Complete" in messages
        assert made["adapter"].closed is True
        assert len(repository.get_discoveries(finished[0])) == 1
    finally:
        worker.deleteLater()
        engine.dispose()


def test_main_window_end_to_end_with_fake_adapter(qapp, tmp_path):
    from PySide6.QtCore import QEventLoop

    engine = build_engine(f"sqlite:///{tmp_path}/e2e.db")
    init_db(engine)
    repository = RavenRepository(engine)
    hit = _repo("https://github.com/o/r")

    def factory():
        return FakeAdapter(by_group={"repository": [hit]})

    settings = Settings(_env_file=None)
    window = MainWindow(settings, repository, adapter_factory=factory)
    try:
        assert window.is_search_running is False
        window.show_page("Search")

        # Poll for completion: the fake adapter finishes in milliseconds,
        # so a signal hookup after click() could miss `finished`.
        loop = QEventLoop()
        poller = QTimer()
        poller.setInterval(50)
        poller.timeout.connect(
            lambda: loop.quit()
            if window.search_page.status_label.text() == "Complete."
            else None
        )
        QTimer.singleShot(15000, loop.quit)
        window.search_page.start_button.click()  # real signal chain
        poller.start()
        loop.exec()
        poller.stop()

        assert window.is_search_running is False
        assert window.stack.currentIndex() == 2  # auto-switched to Results
        assert window.results_page.model.rowCount() == 1
        assert window.dashboard_page.searches_today_text == "1"
        assert window.search_page.status_label.text() == "Complete."
    finally:
        window.close()
        engine.dispose()
