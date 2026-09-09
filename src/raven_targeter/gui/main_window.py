"""PySide6 desktop GUI with secure API configuration and background search."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from PySide6.QtCore import QObject, QSettings, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from raven_targeter.adapters.github import GitHubAdapter
from raven_targeter.adapters.serpapi import SerpAPIAdapter
from raven_targeter.config.credential_store import CredentialStoreError, SecureCredentialStore
from raven_targeter.config.settings import SEARCH_ENGINES, SEARCH_PROVIDERS, Settings
from raven_targeter.models import SearchRequest
from raven_targeter.services.export_service import export_json
from raven_targeter.services.search_service import SearchPipeline


class SearchWorker(QObject):
    done = Signal(object, object)
    failed = Signal(str)

    def __init__(
        self,
        settings: Settings,
        request: SearchRequest,
        *,
        github_token: str | None,
        search_api_key: str | None,
        search_provider: str,
        search_engine: str,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.request = request
        self.github_token = github_token
        self.search_api_key = search_api_key
        self.search_provider = search_provider
        self.search_engine = search_engine

    @Slot()
    def run(self) -> None:
        async def go():
            github = GitHubAdapter(self.github_token) if self.request.sources else None
            web = None
            if self.request.web_search and self.search_provider == "serpapi" and self.search_api_key:
                web = SerpAPIAdapter(
                    self.search_api_key,
                    engine=self.search_engine,
                    base_url=self.settings.search_api_base_url,
                    max_queries=self.settings.search_api_max_queries,
                )
            try:
                return await SearchPipeline().run(self.request, github, web)
            finally:
                if github is not None:
                    await github.aclose()
                if web is not None:
                    await web.aclose()

        try:
            discoveries, errors = asyncio.run(go())
            self.done.emit(discoveries, errors)
        except Exception as exc:  # surfaced to GUI
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ApiTestWorker(QObject):
    finished = Signal(bool, str)

    def __init__(
        self,
        kind: str,
        *,
        token: str | None = None,
        provider: str = "disabled",
        engine: str = "google",
        search_api_key: str | None = None,
        search_base_url: str = "https://serpapi.com/search.json",
    ) -> None:
        super().__init__()
        self.kind = kind
        self.token = token
        self.provider = provider
        self.engine = engine
        self.search_api_key = search_api_key
        self.search_base_url = search_base_url

    @Slot()
    def run(self) -> None:
        async def go() -> tuple[bool, str]:
            if self.kind == "github":
                if not self.token:
                    return False, "GitHub token is missing"
                headers = {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token}",
                    "User-Agent": "Raven-Targeter/0.3",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                try:
                    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                        response = await client.get("https://api.github.com/rate_limit")
                except httpx.HTTPError as exc:
                    return False, f"{type(exc).__name__}: {exc}"
                if response.status_code != 200:
                    return False, f"GitHub API HTTP {response.status_code}"
                try:
                    body = response.json()
                    core = body.get("resources", {}).get("core", {}) if isinstance(body, dict) else {}
                    limit = core.get("limit")
                    remaining = core.get("remaining")
                except ValueError:
                    limit = remaining = None
                return True, f"GitHub API connected — core remaining {remaining}/{limit}"

            if self.kind == "search":
                if self.provider != "serpapi":
                    return False, "Select a Search API provider"
                if not self.search_api_key:
                    return False, "Search API key is missing"
                adapter = SerpAPIAdapter(
                    self.search_api_key,
                    engine=self.engine,
                    base_url=self.search_base_url,
                    max_queries=1,
                )
                try:
                    return await adapter.test_connection()
                finally:
                    await adapter.aclose()

            return False, "Unknown API test"

        try:
            ok, message = asyncio.run(go())
        except Exception as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        self.finished.emit(ok, message)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._results = []
        self._thread: QThread | None = None
        self._worker: SearchWorker | None = None
        self._test_threads: list[QThread] = []
        self._test_workers: list[ApiTestWorker] = []
        self._credential_store = SecureCredentialStore()
        self._ui_settings = QSettings("Raven", "Raven-Targeter")

        self.setWindowTitle("Raven-Targeter")
        self.resize(1200, 760)
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)

        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)
        self._build_search_tab()
        self._build_settings_tab()
        self._refresh_api_status()
        self._update_start_state()

        if not self._resolved_github_token():
            self.tabs.setCurrentWidget(self.settings_tab)
            self.status.setText("Configure your GitHub API token in Settings to enable GitHub search.")

    # ------------------------------------------------------------------ UI
    def _build_search_tab(self) -> None:
        self.search_tab = QWidget()
        self.tabs.addTab(self.search_tab, "Search")
        layout = QVBoxLayout(self.search_tab)

        source_box = QGroupBox("Search Sources")
        source_row = QHBoxLayout(source_box)
        self.github_source = QCheckBox("GitHub API")
        self.github_source.setChecked(True)
        self.web_source = QCheckBox("Web Search API")
        self.web_source.setChecked(False)
        source_row.addWidget(self.github_source)
        source_row.addWidget(self.web_source)
        source_row.addStretch()
        layout.addWidget(source_box)

        form = QFormLayout()
        layout.addLayout(form)
        self.lookback = QSpinBox()
        self.lookback.setRange(1, 365)
        self.lookback.setValue(self.settings.lookback_days)
        self.max_results = QSpinBox()
        self.max_results.setRange(1, 2000)
        self.max_results.setValue(self.settings.max_results_per_source)
        self.keywords = QLineEdit()
        self.keywords.setPlaceholderText("optional, comma-separated")
        form.addRow("Lookback days", self.lookback)
        form.addRow("Final max results", self.max_results)
        form.addRow("Extra keywords", self.keywords)

        target_box = QGroupBox("AI Targets")
        target_row = QHBoxLayout(target_box)
        self.targets: dict[str, QCheckBox] = {}
        for target in self.settings.targets:
            cb = QCheckBox(target)
            cb.setChecked(True)
            self.targets[target] = cb
            target_row.addWidget(cb)
        target_row.addStretch()
        layout.addWidget(target_box)

        action_row = QHBoxLayout()
        self.start = QPushButton("Start Search")
        self.export = QPushButton("Export for Raven-Validator")
        self.export.setEnabled(False)
        self.open_settings = QPushButton("API Settings")
        action_row.addWidget(self.start)
        action_row.addWidget(self.export)
        action_row.addWidget(self.open_settings)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.status = QLabel("Ready")
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Score", "Provider", "Source", "Type", "Title", "Endpoints", "URL"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        self.start.clicked.connect(self._start)
        self.export.clicked.connect(self._export)
        self.open_settings.clicked.connect(lambda: self.tabs.setCurrentWidget(self.settings_tab))
        self.github_source.toggled.connect(self._update_start_state)
        self.web_source.toggled.connect(self._update_start_state)
        for cb in self.targets.values():
            cb.toggled.connect(self._update_start_state)

    def _build_settings_tab(self) -> None:
        self.settings_tab = QWidget()
        self.tabs.addTab(self.settings_tab, "Settings / APIs")
        layout = QVBoxLayout(self.settings_tab)

        intro = QLabel(
            "API credentials are entered by the end user and stored in the operating-system keychain. "
            "Raven does not save tokens in its database or exports."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        github_box = QGroupBox("GitHub API")
        github_form = QFormLayout(github_box)
        self.github_status = QLabel()
        self.github_token_edit = QLineEdit()
        self.github_token_edit.setEchoMode(QLineEdit.Password)
        self.github_token_edit.setPlaceholderText("Paste token to save or replace")
        github_form.addRow("Status", self.github_status)
        github_form.addRow("Personal access token", self.github_token_edit)
        github_buttons = QHBoxLayout()
        self.github_save = QPushButton("Save Securely")
        self.github_test = QPushButton("Test GitHub API")
        self.github_clear = QPushButton("Clear")
        github_buttons.addWidget(self.github_save)
        github_buttons.addWidget(self.github_test)
        github_buttons.addWidget(self.github_clear)
        github_buttons.addStretch()
        github_form.addRow(github_buttons)
        layout.addWidget(github_box)

        search_box = QGroupBox("Web Search API")
        search_form = QFormLayout(search_box)
        self.search_status = QLabel()
        self.search_provider = QComboBox()
        self.search_provider.addItems(list(SEARCH_PROVIDERS))
        saved_provider = str(
            self._ui_settings.value("search/provider", self.settings.search_api_provider)
        ).lower()
        idx = self.search_provider.findText(saved_provider)
        self.search_provider.setCurrentIndex(idx if idx >= 0 else 0)
        self.search_engine = QComboBox()
        self.search_engine.addItems(list(SEARCH_ENGINES))
        saved_engine = str(self._ui_settings.value("search/engine", self.settings.search_api_engine)).lower()
        idx = self.search_engine.findText(saved_engine)
        self.search_engine.setCurrentIndex(idx if idx >= 0 else 0)
        self.search_key_edit = QLineEdit()
        self.search_key_edit.setEchoMode(QLineEdit.Password)
        self.search_key_edit.setPlaceholderText("Paste Search API key to save or replace")
        search_form.addRow("Status", self.search_status)
        search_form.addRow("Provider", self.search_provider)
        search_form.addRow("Engine", self.search_engine)
        search_form.addRow("API key", self.search_key_edit)
        search_buttons = QHBoxLayout()
        self.search_save = QPushButton("Save Securely")
        self.search_test = QPushButton("Test Search API")
        self.search_clear = QPushButton("Clear")
        search_buttons.addWidget(self.search_save)
        search_buttons.addWidget(self.search_test)
        search_buttons.addWidget(self.search_clear)
        search_buttons.addStretch()
        search_form.addRow(search_buttons)
        note = QLabel(
            "Current web-search connector: SerpAPI. The connection test performs one minimal search "
            "and may consume one Search API request. Google engine uses a server-side lookback filter."
        )
        note.setWordWrap(True)
        search_form.addRow(note)
        layout.addWidget(search_box)

        self.api_message = QLabel("")
        self.api_message.setWordWrap(True)
        layout.addWidget(self.api_message)
        layout.addStretch()

        self.github_save.clicked.connect(self._save_github)
        self.github_clear.clicked.connect(self._clear_github)
        self.github_test.clicked.connect(self._test_github)
        self.search_save.clicked.connect(self._save_search)
        self.search_clear.clicked.connect(self._clear_search)
        self.search_test.clicked.connect(self._test_search)
        self.search_provider.currentTextChanged.connect(self._save_search_metadata)
        self.search_engine.currentTextChanged.connect(self._save_search_metadata)

    # -------------------------------------------------------------- secrets
    def _resolved_github_token(self) -> str | None:
        if self.settings.github_token and self.settings.github_token.strip():
            return self.settings.github_token.strip()
        try:
            return self._credential_store.get_github_token()
        except CredentialStoreError:
            return None

    def _resolved_search_key(self) -> str | None:
        if self.settings.search_api_key and self.settings.search_api_key.strip():
            return self.settings.search_api_key.strip()
        try:
            return self._credential_store.get_search_api_key()
        except CredentialStoreError:
            return None

    def _refresh_api_status(self) -> None:
        github = self._resolved_github_token()
        search = self._resolved_search_key()
        github_source = "environment" if self.settings.has_github_token else "OS keychain"
        search_source = "environment" if self.settings.has_search_api_key else "OS keychain"
        self.github_status.setText(
            f"Configured ({github_source})" if github else "Missing — GitHub search disabled"
        )
        provider = self.search_provider.currentText() if hasattr(self, "search_provider") else "disabled"
        if provider == "disabled":
            self.search_status.setText("Disabled")
        else:
            self.search_status.setText(
                f"Configured ({search_source})" if search else "Missing key — web search disabled"
            )

    def _save_github(self) -> None:
        token = self.github_token_edit.text().strip()
        if not token:
            self.api_message.setText("Paste a GitHub token before saving.")
            return
        try:
            self._credential_store.set_github_token(token)
        except (CredentialStoreError, ValueError) as exc:
            self.api_message.setText(f"Could not store GitHub token securely: {exc}")
            return
        self.github_token_edit.clear()
        self.api_message.setText("GitHub token saved to the OS keychain.")
        self._refresh_api_status()
        self._update_start_state()

    def _clear_github(self) -> None:
        if self.settings.has_github_token:
            self.api_message.setText(
                "GITHUB_TOKEN is supplied by the environment. Remove it from the environment/.env to clear it."
            )
            return
        try:
            self._credential_store.clear_github_token()
        except CredentialStoreError as exc:
            self.api_message.setText(f"Could not clear GitHub token: {exc}")
            return
        self.api_message.setText("GitHub token removed from the OS keychain.")
        self._refresh_api_status()
        self._update_start_state()

    def _save_search_metadata(self, *_args: object) -> None:
        self._ui_settings.setValue("search/provider", self.search_provider.currentText())
        self._ui_settings.setValue("search/engine", self.search_engine.currentText())
        self._refresh_api_status()
        self._update_start_state()

    def _save_search(self) -> None:
        self._save_search_metadata()
        if self.search_provider.currentText() == "disabled":
            self.api_message.setText("Web Search API is disabled. Provider/engine preference saved.")
            return
        key = self.search_key_edit.text().strip()
        if not key:
            self.api_message.setText("Paste a Search API key before saving.")
            return
        try:
            self._credential_store.set_search_api_key(key)
        except (CredentialStoreError, ValueError) as exc:
            self.api_message.setText(f"Could not store Search API key securely: {exc}")
            return
        self.search_key_edit.clear()
        self.api_message.setText("Search API key saved to the OS keychain.")
        self._refresh_api_status()
        self._update_start_state()

    def _clear_search(self) -> None:
        if self.settings.has_search_api_key:
            self.api_message.setText(
                "SEARCH_API_KEY is supplied by the environment. Remove it from the environment/.env to clear it."
            )
            return
        try:
            self._credential_store.clear_search_api_key()
        except CredentialStoreError as exc:
            self.api_message.setText(f"Could not clear Search API key: {exc}")
            return
        self.api_message.setText("Search API key removed from the OS keychain.")
        self._refresh_api_status()
        self._update_start_state()

    # --------------------------------------------------------------- API test
    def _run_api_test(self, worker: ApiTestWorker, button: QPushButton) -> None:
        button.setEnabled(False)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def finished(ok: bool, message: str) -> None:
            self.api_message.setText(("OK — " if ok else "Failed — ") + message)
            button.setEnabled(True)
            thread.quit()

        worker.finished.connect(finished)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._test_threads.remove(thread) if thread in self._test_threads else None)
        self._test_threads.append(thread)
        self._test_workers.append(worker)
        worker.finished.connect(
            lambda _ok, _message: self._test_workers.remove(worker)
            if worker in self._test_workers
            else None
        )
        thread.start()

    def _test_github(self) -> None:
        token = self.github_token_edit.text().strip() or self._resolved_github_token()
        self._run_api_test(ApiTestWorker("github", token=token), self.github_test)

    def _test_search(self) -> None:
        provider = self.search_provider.currentText()
        key = self.search_key_edit.text().strip() or self._resolved_search_key()
        self._run_api_test(
            ApiTestWorker(
                "search",
                provider=provider,
                engine=self.search_engine.currentText(),
                search_api_key=key,
                search_base_url=self.settings.search_api_base_url,
            ),
            self.search_test,
        )

    # --------------------------------------------------------------- searching
    def _update_start_state(self) -> None:
        if not hasattr(self, "start"):
            return
        selected_targets = any(cb.isChecked() for cb in self.targets.values())
        selected_source = self.github_source.isChecked() or self.web_source.isChecked()
        github_ok = not self.github_source.isChecked() or bool(self._resolved_github_token())
        provider = self.search_provider.currentText() if hasattr(self, "search_provider") else "disabled"
        web_ok = not self.web_source.isChecked() or (
            provider != "disabled" and bool(self._resolved_search_key())
        )
        self.start.setEnabled(selected_targets and selected_source and github_ok and web_ok and self._thread is None)

    def _start(self) -> None:
        github_token = self._resolved_github_token()
        search_key = self._resolved_search_key()
        if self.github_source.isChecked() and not github_token:
            self.tabs.setCurrentWidget(self.settings_tab)
            self.status.setText("GitHub token missing. Configure it in Settings / APIs.")
            return
        if self.web_source.isChecked() and (
            self.search_provider.currentText() == "disabled" or not search_key
        ):
            self.tabs.setCurrentWidget(self.settings_tab)
            self.status.setText("Search API is not configured. Configure it in Settings / APIs.")
            return

        req = SearchRequest(
            targets=[target for target, cb in self.targets.items() if cb.isChecked()],
            keywords=[x.strip() for x in self.keywords.text().split(",") if x.strip()],
            sources=["repository", "code", "issue", "pull_request"] if self.github_source.isChecked() else [],
            web_search=self.web_source.isChecked(),
            lookback_days=self.lookback.value(),
            max_results_per_source=self.max_results.value(),
        )
        self.start.setEnabled(False)
        source_names = []
        if self.github_source.isChecked():
            source_names.append("GitHub")
        if self.web_source.isChecked():
            source_names.append("Web")
        self.status.setText(f"Searching {' + '.join(source_names)}…")
        self._thread = QThread(self)
        self._worker = SearchWorker(
            self.settings,
            req,
            github_token=github_token,
            search_api_key=search_key,
            search_provider=self.search_provider.currentText(),
            search_engine=self.search_engine.currentText(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._done)
        self._worker.failed.connect(self._failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._search_thread_finished)
        self._thread.start()

    def _search_thread_finished(self) -> None:
        self._worker = None
        self._thread = None
        self._update_start_state()

    def _done(self, discoveries, errors) -> None:
        self._results = discoveries
        self.table.setRowCount(len(discoveries))
        for row, discovery in enumerate(discoveries):
            values = [
                f"{discovery.total_score:.1f}",
                discovery.provider or "",
                discovery.source,
                discovery.classification,
                discovery.title,
                str(len(discovery.candidate_endpoints)),
                discovery.url,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        self.status.setText(
            f"Complete: {len(discoveries)} results, {len(errors)} source error(s)"
        )
        self.export.setEnabled(bool(discoveries))

    def _failed(self, message: str) -> None:
        self.status.setText(message)

    def _export(self) -> None:
        path = export_json(
            self._results, Path("exports") / "raven-discovery-export-v1.json"
        )
        self.status.setText(f"Exported: {path}")


def run_app(settings: Settings) -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(settings)
    window.show()
    return app.exec()
