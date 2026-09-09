"""Result detail dialog: full discovery view with open/copy actions."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from raven_targeter.models import Discovery


def _format_datetime(value: object) -> str:
    if value is None:
        return "—"
    return str(value)


class ResultDetailDialog(QDialog):
    """Modal detail view. Export wiring lands in M6 via signal."""

    export_requested = Signal(Discovery)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Result detail")
        self.resize(600, 500)
        self._discovery: Discovery | None = None
        self._url = ""

        self._title = QLabel("")
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-size: 15px; font-weight: bold;")
        self._url_label = QLabel("")
        self._url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._meta = QLabel("")
        self._meta.setWordWrap(True)
        self._scores = QLabel("")
        self._description = QLabel("")
        self._description.setWordWrap(True)
        self._terms = QListWidget()
        self._evidence = QListWidget()

        form = QFormLayout()
        form.addRow("Scores:", self._scores)
        form.addRow("Meta:", self._meta)
        form.addRow("Description:", self._description)
        form.addRow("Matched terms:", self._terms)
        form.addRow("Evidence:", self._evidence)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open in browser")
        self.copy_button = QPushButton("Copy URL")
        self.export_button = QPushButton("Export selected")
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)

        self.open_button.clicked.connect(self._on_open)
        self.copy_button.clicked.connect(self._on_copy)
        self.export_button.clicked.connect(self._on_export)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._url_label)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def show_discovery(self, discovery: Discovery) -> None:
        """Populate every field from a discovery (redacted upstream)."""
        self._discovery = discovery
        self._url = discovery.url
        self._title.setText(discovery.title)
        self._url_label.setText(discovery.url)
        dates = (
            f"created {_format_datetime(discovery.created_at)} · "
            f"updated {_format_datetime(discovery.updated_at)} · "
            f"pushed {_format_datetime(discovery.pushed_at)}"
        )
        self._meta.setText(
            f"{discovery.source} / {discovery.source_type} · "
            f"{discovery.provider or '—'} · by {discovery.author or '—'} · "
            f"{discovery.classification} · ★ {discovery.stars} · "
            f"⑂ {discovery.forks}\n{dates}"
        )
        self._scores.setText(
            f"total {discovery.total_score:.0f} "
            f"(relevance {discovery.relevance_score:.0f} · "
            f"freshness {discovery.freshness_score:.0f} · "
            f"implementation {discovery.implementation_score:.0f} · "
            f"engagement {discovery.engagement_score:.0f} · "
            f"confidence {discovery.confidence_score:.0f})"
        )
        self._description.setText(discovery.description or "—")
        self._terms.clear()
        self._terms.addItems(discovery.matched_terms)
        self._evidence.clear()
        self._evidence.addItems(discovery.evidence)

    @property
    def current_url(self) -> str:
        """URL of the displayed discovery (for tests)."""
        return self._url

    def _on_open(self) -> None:
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    def _on_copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None and self._url:
            clipboard.setText(self._url)

    def _on_export(self) -> None:
        if self._discovery is not None:
            self.export_requested.emit(self._discovery)
