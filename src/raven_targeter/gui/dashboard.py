"""Dashboard page: run history and headline stats at a glance."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from raven_targeter.database.repository import RunSummary


class DashboardPage(QWidget):
    """Stat cards fed by detached run summaries. M5 wires the refresh."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._searches_today = QLabel("0")
        self._new_discoveries = QLabel("0")
        self._last_run = QLabel("Never")
        self._last_errors = QLabel("0")

        for label in (
            self._searches_today,
            self._new_discoveries,
            self._last_run,
            self._last_errors,
        ):
            label.setStyleSheet("font-size: 18px; font-weight: bold;")

        layout = QHBoxLayout(self)
        layout.addWidget(self._card("Searches today", self._searches_today))
        layout.addWidget(self._card("New discoveries (last run)", self._new_discoveries))
        layout.addWidget(self._card("Last run", self._last_run))
        layout.addWidget(self._card("Errors (last run)", self._last_errors))
        layout.addStretch(1)

    @staticmethod
    def _card(title: str, value: QLabel) -> QGroupBox:
        box = QGroupBox(title)
        form = QFormLayout(box)
        form.addRow(value)
        return box

    def refresh(self, runs: list[RunSummary]) -> None:
        """Update cards from newest-first run summaries."""
        if not runs:
            self._searches_today.setText("0")
            self._new_discoveries.setText("0")
            self._last_run.setText("Never")
            self._last_errors.setText("0")
            return
        today = runs[0].started_at.date()
        searches_today = sum(1 for run in runs if run.started_at.date() == today)
        latest = runs[0]
        self._searches_today.setText(str(searches_today))
        self._new_discoveries.setText(str(latest.accepted_count))
        self._last_run.setText(latest.started_at.strftime("%Y-%m-%d %H:%M UTC"))
        self._last_errors.setText(str(latest.error_count))

    # Read-only accessors for tests and M5 status wiring.
    @property
    def searches_today_text(self) -> str:
        """Current 'Searches today' card text."""
        return self._searches_today.text()

    @property
    def last_run_text(self) -> str:
        """Current 'Last run' card text."""
        return self._last_run.text()
