"""Search page: target/parameter controls plus run progress.

Emits :attr:`search_requested` with a validated
:class:`~raven_targeter.models.SearchRequest` when Start is pressed, and
:attr:`cancel_requested` on Cancel. M5 connects these to the search
service; M4 exercises them structurally (see ``tests/test_gui.py``).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from raven_targeter.config.settings import Settings
from raven_targeter.config.targets import TARGET_IDS, display_name
from raven_targeter.models import SearchRequest

_KEYWORD_SEPARATOR = ","


class SearchPage(QWidget):
    """Search controls. Emits requests; never runs network I/O itself."""

    search_requested = Signal(SearchRequest)
    cancel_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        targets_box = QGroupBox("Targets")
        targets_layout = QHBoxLayout(targets_box)
        self.target_checks: dict[str, QCheckBox] = {}
        for target in TARGET_IDS:
            check = QCheckBox(display_name(target))
            check.setChecked(target in settings.targets)
            self.target_checks[target] = check
            targets_layout.addWidget(check)

        params_box = QGroupBox("Parameters")
        params_layout = QFormLayout(params_box)
        self.lookback_spin = QSpinBox()
        self.lookback_spin.setRange(1, 365)
        self.lookback_spin.setValue(settings.lookback_days)
        params_layout.addRow("Lookback days:", self.lookback_spin)

        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(1, 1000)
        self.max_results_spin.setValue(settings.max_results_per_source)
        params_layout.addRow("Max results per source:", self.max_results_spin)

        self.keywords_edit = QLineEdit()
        self.keywords_edit.setPlaceholderText("optional, comma-separated")
        params_layout.addRow("Keywords:", self.keywords_edit)

        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setRange(0.0, 100.0)
        self.min_score_spin.setSingleStep(5.0)
        self.min_score_spin.setValue(0.0)
        params_layout.addRow("Minimum score:", self.min_score_spin)

        buttons_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Search")
        self.cancel_button = QPushButton("Cancel Search")
        self.cancel_button.setEnabled(False)
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addStretch(1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label = QLabel("Idle.")

        self.start_button.clicked.connect(self._on_start)
        self.cancel_button.clicked.connect(self._on_cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(targets_box)
        layout.addWidget(params_box)
        layout.addLayout(buttons_layout)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    # -- request building -------------------------------------------------

    def selected_targets(self) -> list[str]:
        """Canonical IDs of the checked targets, in canonical order."""
        return [t for t in TARGET_IDS if self.target_checks[t].isChecked()]

    def entered_keywords(self) -> list[str]:
        """User keywords split on commas, blanks dropped."""
        return [
            part.strip()
            for part in self.keywords_edit.text().split(_KEYWORD_SEPARATOR)
            if part.strip()
        ]

    def build_request(self) -> SearchRequest:
        """Build a validated request from the current control values."""
        return SearchRequest(
            targets=self.selected_targets(),
            keywords=self.entered_keywords(),
            lookback_days=self.lookback_spin.value(),
            max_results_per_source=self.max_results_spin.value(),
            minimum_score=self.min_score_spin.value(),
        )

    # -- slots for M5 -------------------------------------------------------

    def set_running(self, running: bool) -> None:
        """Toggle controls for an in-flight search."""
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if running:
            self.progress_bar.setValue(0)

    def set_status(self, text: str) -> None:
        """Show a pipeline status line (e.g. 'Searching repositories…')."""
        self.status_label.setText(text)

    def set_progress(self, percent: int) -> None:
        """Set the progress bar (0-100, clamped)."""
        self.progress_bar.setValue(max(0, min(100, percent)))

    # -- internal -------------------------------------------------------------

    def _on_start(self) -> None:
        self.search_requested.emit(self.build_request())

    def _on_cancel(self) -> None:
        self.cancel_requested.emit()
