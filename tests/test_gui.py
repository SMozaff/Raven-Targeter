"""Offscreen structural tests for the M4 GUI shell.

Run headless via ``QT_QPA_PLATFORM=offscreen`` (set below before any
QApplication exists). These verify structure, signals, filters, and that
no secret values reach the screen — not visual styling. Run
``python app.py`` locally for visual verification.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from raven_targeter.config.settings import Settings
from raven_targeter.database.database import build_engine, init_db
from raven_targeter.database.repository import RavenRepository, RunSummary
from raven_targeter.gui.dashboard import DashboardPage
from raven_targeter.gui.main_window import MainWindow
from raven_targeter.gui.result_detail import ResultDetailDialog
from raven_targeter.gui.results_page import ResultsPage
from raven_targeter.gui.search_page import SearchPage
from raven_targeter.gui.settings_page import SettingsPage
from raven_targeter.models import Discovery


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def settings():
    return Settings(_env_file=None)


@pytest.fixture
def repository():
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    repository = RavenRepository(engine)
    yield repository
    engine.dispose()


def _discovery(url: str, provider: str = "openai", score: float = 50.0) -> Discovery:
    ref = datetime.now(UTC)
    return Discovery(
        title=f"repo {url}",
        url=url,
        provider=provider,
        author="someone",
        created_at=ref - timedelta(days=1),
        pushed_at=ref - timedelta(hours=2),
        stars=5,
        matched_terms=[provider],
        evidence=["Matched repository search"],
        relevance_score=score,
        freshness_score=score,
        implementation_score=score,
        engagement_score=score,
        confidence_score=score,
        classification="api-wrapper",
        canonical_url=url,
        repo_identity="github.com/o/r",
    )


# -- main window -------------------------------------------------------------


def test_main_window_has_four_pages(qapp, settings, repository):
    window = MainWindow(settings, repository)
    try:
        assert window.stack.count() == 4
        assert window.nav.count() == 4
        for name in ("Dashboard", "Search", "Results", "Settings"):
            window.show_page(name)
            assert window.stack.currentWidget() is not None
        assert window.stack.currentIndex() == 3
    finally:
        window.close()


def test_main_window_unknown_page_raises(qapp, settings, repository):
    window = MainWindow(settings, repository)
    try:
        with pytest.raises(ValueError):
            window.show_page("Nope")
    finally:
        window.close()


# -- search page ---------------------------------------------------------------


def test_search_page_defaults_from_settings(qapp):
    settings = Settings(_env_file=None, lookback_days=7)
    page = SearchPage(settings)
    try:
        assert page.selected_targets() == list(settings.targets)
        assert page.lookback_spin.value() == 7
        request = page.build_request()
        assert request.lookback_days == 7
        assert request.max_results_per_source == settings.max_results_per_source
    finally:
        page.close()


def test_search_page_emits_search_and_cancel(qapp, settings):
    page = SearchPage(settings)
    try:
        received = []
        page.search_requested.connect(received.append)
        cancelled = []
        page.cancel_requested.connect(lambda: cancelled.append(True))
        page.keywords_edit.setText("fastapi, proxy")
        page.start_button.click()
        assert len(received) == 1
        assert received[0].keywords == ["fastapi", "proxy"]
        page.set_running(True)  # cancel is only clickable mid-run
        page.cancel_button.click()
        assert cancelled == [True]
    finally:
        page.close()


def test_search_page_running_toggles_buttons(qapp, settings):
    page = SearchPage(settings)
    try:
        page.set_running(True)
        assert page.start_button.isEnabled() is False
        assert page.cancel_button.isEnabled() is True
        page.set_status("Searching repositories")
        assert page.status_label.text() == "Searching repositories"
        page.set_progress(150)
        assert page.progress_bar.value() == 100  # clamped
        page.set_running(False)
        assert page.start_button.isEnabled() is True
    finally:
        page.close()


# -- results page ---------------------------------------------------------------


def test_results_page_populates_rows(qapp):
    page = ResultsPage()
    try:
        items = [
            _discovery("https://github.com/o/low", score=10.0),
            _discovery("https://github.com/o/high", score=90.0),
        ]
        page.set_discoveries(items)
        assert page.model.rowCount() == 2
        assert page.visible_row_count == 2
        assert page.table.isSortingEnabled()
        assert page.selected_discovery() is None
    finally:
        page.close()


def test_results_page_provider_filter(qapp):
    page = ResultsPage()
    try:
        page.set_discoveries(
            [
                _discovery("https://github.com/o/a", provider="openai"),
                _discovery("https://github.com/o/b", provider="grok"),
            ]
        )
        page.provider_combo.setCurrentText("grok")
        assert page.visible_row_count == 1
        page.provider_combo.setCurrentText("All")
        assert page.visible_row_count == 2
    finally:
        page.close()


def test_results_page_min_score_filter(qapp):
    page = ResultsPage()
    try:
        page.set_discoveries(
            [
                _discovery("https://github.com/o/a", score=10.0),
                _discovery("https://github.com/o/b", score=90.0),
            ]
        )
        page.min_score_spin.setValue(50.0)
        assert page.visible_row_count == 1
    finally:
        page.close()


def test_results_page_selection_and_detail_signal(qapp):
    page = ResultsPage()
    try:
        item = _discovery("https://github.com/o/a")
        page.set_discoveries([item])
        page.table.selectRow(0)
        selected = page.selected_discovery()
        assert selected is not None
        assert selected.url == "https://github.com/o/a"

        emitted = []
        page.detail_requested.connect(emitted.append)
        page._on_double_click(page.proxy.index(0, 0))
        assert emitted == [item]
    finally:
        page.close()


def test_results_page_recency_toggle(qapp):
    page = ResultsPage()
    try:
        ref = datetime.now(UTC)
        recent = _discovery("https://github.com/o/recent")
        stale = Discovery(
            title="stale",
            url="https://github.com/o/stale",
            provider="openai",
            created_at=ref - timedelta(days=200),
            pushed_at=ref - timedelta(days=200),
            canonical_url="https://github.com/o/stale",
        )
        page.set_discoveries([recent, stale])
        page.new_check.setChecked(True)
        assert page.visible_row_count == 1
    finally:
        page.close()


# -- detail dialog ---------------------------------------------------------------


def test_detail_dialog_populates_and_exports(qapp):
    dialog = ResultDetailDialog()
    try:
        item = _discovery("https://github.com/o/a")
        dialog.show_discovery(item)
        assert item.title in dialog._title.text()
        assert dialog.current_url == "https://github.com/o/a"

        exported = []
        dialog.export_requested.connect(exported.append)
        dialog.export_button.click()
        assert exported == [item]

        dialog.copy_button.click()  # must not crash headless
    finally:
        dialog.close()


# -- settings page -----------------------------------------------------------------


def test_settings_page_masks_token_value(qapp):
    page = SettingsPage()
    try:
        settings = Settings(_env_file=None, github_token="ghp_secretvalue123")
        page.refresh(settings)
        assert page.token_status_text == "Configured"
        for label in (
            page._token_status,
            page._targets,
            page._lookback,
            page._max_results,
            page._db_url,
            page._log_level,
        ):
            assert "ghp_secretvalue123" not in label.text()

        page.refresh(Settings(_env_file=None))
        assert page.token_status_text == "Missing"
    finally:
        page.close()


# -- dashboard -----------------------------------------------------------------------


def test_dashboard_empty_and_populated(qapp):
    page = DashboardPage()
    try:
        page.refresh([])
        assert page.last_run_text == "Never"
        now = datetime.now(UTC)
        runs = [
            RunSummary(
                id="b",
                started_at=now,
                completed_at=now,
                status="completed",
                lookback_days=10,
                targets=["openai"],
                sources=["repository"],
                candidate_count=20,
                accepted_count=5,
                error_count=0,
            ),
            RunSummary(
                id="a",
                started_at=now - timedelta(days=3),
                completed_at=now - timedelta(days=3),
                status="completed",
                lookback_days=10,
                targets=["openai"],
                sources=["repository"],
                candidate_count=9,
                accepted_count=2,
                error_count=1,
            ),
        ]
        page.refresh(runs)
        assert page.searches_today_text == "1"
        assert "UTC" in page.last_run_text
    finally:
        page.close()
