"""Settings page: read-only view of effective configuration.

The GitHub token is shown as Configured/Missing only — its value is
never displayed, logged, or stored anywhere on this page.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QWidget,
)

from raven_targeter.config.settings import Settings


class SettingsPage(QWidget):
    """Displays effective settings. M5 may add editing; M4 is display-only."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._token_status = QLabel("Missing")
        self._targets = QLabel("")
        self._lookback = QLabel("")
        self._max_results = QLabel("")
        self._db_url = QLabel("")
        self._log_level = QLabel("")

        form = QFormLayout(self)
        form.addRow("GitHub token status:", self._token_status)
        form.addRow("Targets:", self._targets)
        form.addRow("Lookback days:", self._lookback)
        form.addRow("Max results per source:", self._max_results)
        form.addRow("Database:", self._db_url)
        form.addRow("Log level:", self._log_level)

    def refresh(self, settings: Settings) -> None:
        """Update all rows from settings. The token value is never shown."""
        self._token_status.setText(
            "Configured" if settings.has_github_token else "Missing"
        )
        self._targets.setText(", ".join(settings.targets))
        self._lookback.setText(str(settings.lookback_days))
        self._max_results.setText(str(settings.max_results_per_source))
        self._db_url.setText(settings.db_url)
        self._log_level.setText(settings.log_level)

    @property
    def token_status_text(self) -> str:
        """Current token status text (for tests and status bars)."""
        return self._token_status.text()
