"""Main window: sidebar navigation across Dashboard/Search/Results/Settings.

M5 wires end-to-end search: the SearchPage's ``search_requested`` signal
starts a :class:`~raven_targeter.services.search_service.SearchWorker`
on a dedicated ``QThread``; worker signals stream progress and
discoveries into the Search/Results pages and refresh the Dashboard on
completion. Network and database work never runs on the Qt UI thread.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from raven_targeter.adapters.github import GitHubAdapter
from raven_targeter.config.settings import Settings
from raven_targeter.database.database import build_engine, init_db
from raven_targeter.database.repository import RavenRepository
from raven_targeter.gui.dashboard import DashboardPage
from raven_targeter.gui.result_detail import ResultDetailDialog
from raven_targeter.gui.results_page import ResultsPage
from raven_targeter.gui.search_page import SearchPage
from raven_targeter.gui.settings_page import SettingsPage
from raven_targeter.models import Discovery, SearchRequest
from raven_targeter.services.export_service import export_discoveries
from raven_targeter.services.search_service import SearchWorker

_PAGE_TITLES = ("Dashboard", "Search", "Results", "Settings")


class MainWindow(QMainWindow):
    """Root window holding navigation, pages, and the search worker thread."""

    def __init__(
        self,
        settings: Settings,
        repository: RavenRepository,
        adapter_factory: Callable[[], GitHubAdapter] | None = None,
        exports_dir: str | Path = "exports",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.repository = repository
        self._adapter_factory = adapter_factory
        self._exports_dir = exports_dir
        self._thread: QThread | None = None
        self._worker: SearchWorker | None = None

        self.setWindowTitle("Raven-Targeter")
        self.resize(1100, 700)
        self.statusBar().showMessage("Idle.")

        self.nav = QListWidget()
        self.nav.addItems(_PAGE_TITLES)
        self.nav.setFixedWidth(160)
        self.nav.setCurrentRow(0)

        self.dashboard_page = DashboardPage()
        self.search_page = SearchPage(settings)
        self.results_page = ResultsPage()
        self.settings_page = SettingsPage()
        self.settings_page.refresh(settings)
        self._refresh_dashboard()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.search_page)
        self.stack.addWidget(self.results_page)
        self.stack.addWidget(self.settings_page)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.search_page.search_requested.connect(self._on_search_requested)
        self.search_page.cancel_requested.connect(self._on_cancel_requested)
        self.results_page.detail_requested.connect(self._on_detail_requested)
        self.results_page.export_requested.connect(self._on_export_visible)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(self.nav)
        layout.addWidget(self.stack, stretch=1)
        self.setCentralWidget(central)

    def show_page(self, name: str) -> None:
        """Switch to a page by title (e.g. ``show_page("Results")``)."""
        try:
            self.nav.setCurrentRow(_PAGE_TITLES.index(name))
        except ValueError as exc:
            raise ValueError(f"Unknown page: {name!r}") from exc

    # -- search wiring -------------------------------------------------------

    @property
    def is_search_running(self) -> bool:
        """True while a worker thread is active."""
        return self._thread is not None and self._thread.isRunning()

    def _on_search_requested(self, request: SearchRequest) -> None:
        if self.is_search_running:
            return
        self.search_page.set_running(True)
        self.results_page.set_discoveries([])

        self._thread = QThread(self)
        self._worker = SearchWorker(
            self.settings, self.repository, self._adapter_factory
        )
        self._worker.moveToThread(self._thread)
        assert self._thread is not None and self._worker is not None

        self._thread.started.connect(lambda: self._worker.run(request))
        self._worker.progress_message.connect(self.search_page.set_status)
        self._worker.progress_percent.connect(self.search_page.set_progress)
        self._worker.discovery_found.connect(self._on_discovery_found)
        self._worker.finished.connect(self._on_search_finished)
        self._worker.failed.connect(self._on_search_failed)
        self._worker.search_cancelled.connect(self._on_search_cancelled)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_cancel_requested(self) -> None:
        if self._worker is not None:
            self.search_page.set_status("Cancelling…")
            self._worker.cancel()

    def _on_discovery_found(self, discovery: Discovery) -> None:
        self.results_page.append_discovery(discovery)

    def _on_search_finished(self, run_id: str) -> None:
        self._teardown_thread()
        self.search_page.set_running(False)
        self.search_page.set_status("Complete.")
        self.search_page.set_progress(100)
        self.results_page.set_discoveries(
            self.repository.get_discoveries(run_id)
        )
        self._refresh_dashboard()
        self.show_page("Results")

    def _on_search_failed(self, message: str) -> None:
        self._teardown_thread()
        self.search_page.set_running(False)
        self.search_page.set_status(f"Search failed: {message}")
        self._refresh_dashboard()

    def _on_search_cancelled(self) -> None:
        self._teardown_thread()
        self.search_page.set_running(False)
        self.search_page.set_status("Cancelled.")
        self._refresh_dashboard()

    def _on_detail_requested(self, discovery: Discovery) -> None:
        dialog = ResultDetailDialog(self)
        dialog.export_requested.connect(self._on_export_single)
        dialog.show_discovery(discovery)
        dialog.exec()

    # -- export --------------------------------------------------------------

    def _on_export_single(self, discovery: Discovery) -> None:
        """Export one discovery (detail dialog) as JSON."""
        try:
            path = export_discoveries([discovery], self._exports_dir, "json")
        except OSError as exc:
            self.statusBar().showMessage(f"Export failed: {exc}")
            return
        self.statusBar().showMessage(f"Exported 1 result to {path}.")

    def _on_export_visible(self, format: str) -> None:
        """Export the currently filtered results in the requested format."""
        items = self.results_page.visible_discoveries()
        try:
            path = export_discoveries(items, self._exports_dir, format)
        except (OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Export failed: {exc}")
            return
        self.statusBar().showMessage(f"Exported {len(items)} result(s) to {path}.")

    def _refresh_dashboard(self) -> None:
        self.dashboard_page.refresh(self.repository.list_runs())

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        self._worker = None

    def closeEvent(self, event: object) -> None:  # type: ignore[override]
        """Cancel any running search before the window closes."""
        if self._worker is not None:
            self._worker.cancel()
        self._teardown_thread()
        super().closeEvent(event)


def run_app(settings: Settings) -> int:
    """Create the QApplication, storage, and main window; run the event loop."""
    app = QApplication.instance() or QApplication(sys.argv)

    engine = build_engine(settings.db_url)
    init_db(engine)
    repository = RavenRepository(engine)

    window = MainWindow(settings, repository)
    window.show()
    return app.exec()
