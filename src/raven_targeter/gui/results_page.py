"""Results page: sortable discovery table with display filters.

Filtering here is presentation-level (a fixed 10-day window for the
recency toggles); exact run-window filtering belongs to the search
request and repository query in M5. The page stores full
:class:`~raven_targeter.models.Discovery` objects keyed by ID so detail
views and export (M6) never re-derive data from cell text.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from raven_targeter.core.date_validator import classify_repo_dates
from raven_targeter.models import CLASSIFICATIONS, Discovery
from raven_targeter.utils.dates import now_utc

_COLUMNS = (
    "Score",
    "Provider",
    "Source",
    "Type",
    "Title",
    "Author",
    "Created",
    "Updated",
    "Stars",
    "Confidence",
)

_TIME_RANGES = ("All time", "Last 24 hours", "Last 3 days", "Last 10 days")
_TIME_RANGE_DAYS = (0, 1, 3, 10)
_DISPLAY_LOOKBACK_DAYS = 10


class _SortItem(QStandardItem):
    """Table cell with a proper sort key (numbers/dates sort numerically)."""

    def __init__(self, text: str, sort_key: float | str) -> None:
        super().__init__(text)
        self._sort_key = sort_key
        self.setEditable(False)

    def __lt__(self, other: object) -> bool:
        if isinstance(other, _SortItem):
            if type(self._sort_key) is type(other._sort_key):
                return self._sort_key < other._sort_key
            return str(self._sort_key) < str(other._sort_key)
        return super().__lt__(other)


class ResultsFilterProxy(QSortFilterProxyModel):
    """Accepts rows matching the page's current filter criteria."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.provider = "All"
        self.classification = "All"
        self.time_range_days = 0
        self.newly_created_only = False
        self.recently_active_only = False
        self.min_score = 0.0
        self._discoveries: dict[str, Discovery] = {}

    def set_discoveries(self, discoveries: dict[str, Discovery]) -> None:
        """Share the page's ID-keyed discovery map for row evaluation."""
        self._discoveries = discoveries
        self.invalidate()

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        discovery_id = model.data(model.index(source_row, 0), Qt.UserRole)
        discovery = self._discoveries.get(str(discovery_id))
        if discovery is None:
            return False
        if self.provider != "All" and discovery.provider != self.provider:
            return False
        if (
            self.classification != "All"
            and discovery.classification != self.classification
        ):
            return False
        if discovery.total_score < self.min_score:
            return False
        now = now_utc()
        if self.time_range_days > 0:
            recent = [
                dt
                for dt in (
                    discovery.created_at,
                    discovery.pushed_at,
                    discovery.updated_at,
                )
                if dt is not None
                and (now - dt).total_seconds() <= self.time_range_days * 86400
            ]
            if not recent:
                return False
        if self.newly_created_only or self.recently_active_only:
            status = classify_repo_dates(
                discovery.created_at,
                discovery.pushed_at,
                _DISPLAY_LOOKBACK_DAYS,
                updated_at=discovery.updated_at,
                reference=now,
            )
            if self.newly_created_only and not status.newly_created:
                return False
            if self.recently_active_only and not status.recently_active:
                return False
        return True


def _format_date(value: datetime | None) -> tuple[str, float]:
    if value is None:
        return "—", -1.0
    return value.strftime("%Y-%m-%d"), value.timestamp()


class ResultsPage(QWidget):
    """Sortable, filterable results table emitting detail requests."""

    detail_requested = Signal(Discovery)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._discoveries: dict[str, Discovery] = {}

        # -- filter bar --
        filter_layout = QHBoxLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("All")
        self.classification_combo = QComboBox()
        self.classification_combo.addItem("All")
        self.classification_combo.addItems(list(CLASSIFICATIONS))
        self.time_combo = QComboBox()
        self.time_combo.addItems(list(_TIME_RANGES))
        self.new_check = QCheckBox("Newly created")
        self.active_check = QCheckBox("Recently active")
        self.min_score_spin = QDoubleSpinBox()
        self.min_score_spin.setRange(0.0, 100.0)
        self.min_score_spin.setSingleStep(5.0)

        filter_layout.addWidget(QLabel("Provider:"))
        filter_layout.addWidget(self.provider_combo)
        filter_layout.addWidget(QLabel("Classification:"))
        filter_layout.addWidget(self.classification_combo)
        filter_layout.addWidget(QLabel("Time:"))
        filter_layout.addWidget(self.time_combo)
        filter_layout.addWidget(self.new_check)
        filter_layout.addWidget(self.active_check)
        filter_layout.addWidget(QLabel("Min score:"))
        filter_layout.addWidget(self.min_score_spin)
        filter_layout.addStretch(1)

        # -- table --
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(list(_COLUMNS))
        self.proxy = ResultsFilterProxy()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.doubleClicked.connect(self._on_double_click)

        self.provider_combo.currentTextChanged.connect(self._apply_filters)
        self.classification_combo.currentTextChanged.connect(self._apply_filters)
        self.time_combo.currentIndexChanged.connect(self._apply_filters)
        self.new_check.toggled.connect(self._apply_filters)
        self.active_check.toggled.connect(self._apply_filters)
        self.min_score_spin.valueChanged.connect(self._apply_filters)

        layout = QVBoxLayout(self)
        layout.addLayout(filter_layout)
        layout.addWidget(self.table)

    # -- data --------------------------------------------------------------

    def set_discoveries(self, discoveries: list[Discovery]) -> None:
        """Replace table contents; refresh provider options."""
        self._discoveries = {d.id: d for d in discoveries}
        providers = sorted({d.provider for d in discoveries if d.provider})
        current = self.provider_combo.currentText()
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        self.provider_combo.addItem("All")
        self.provider_combo.addItems(providers)
        self.provider_combo.setCurrentText(
            current if current in (["All"] + providers) else "All"
        )
        self.provider_combo.blockSignals(False)

        self.model.removeRows(0, self.model.rowCount())
        for discovery in discoveries:
            self.model.appendRow(self._row(discovery))
        self.proxy.set_discoveries(self._discoveries)

    def append_discovery(self, discovery: Discovery) -> None:
        """Append one streamed discovery (M5 live results)."""
        if discovery.id in self._discoveries:
            return
        self._discoveries[discovery.id] = discovery
        self.model.appendRow(self._row(discovery))
        self.proxy.set_discoveries(self._discoveries)

    def _row(self, discovery: Discovery) -> list[QStandardItem]:
        created_text, created_key = _format_date(discovery.created_at)
        updated_text, updated_key = _format_date(discovery.updated_at)
        stars_text = str(discovery.stars) if discovery.stars is not None else "—"
        stars_key: float | str = (
            float(discovery.stars) if discovery.stars is not None else -1.0
        )
        cells = [
            _SortItem(f"{discovery.total_score:.0f}", discovery.total_score),
            _SortItem(discovery.provider or "—", discovery.provider or ""),
            _SortItem(discovery.source, discovery.source),
            _SortItem(discovery.source_type, discovery.source_type),
            _SortItem(discovery.title, discovery.title.lower()),
            _SortItem(discovery.author or "—", (discovery.author or "").lower()),
            _SortItem(created_text, created_key),
            _SortItem(updated_text, updated_key),
            _SortItem(stars_text, stars_key),
            _SortItem(f"{discovery.confidence_score:.0f}", discovery.confidence_score),
        ]
        cells[0].setData(discovery.id, Qt.UserRole)
        return cells

    def selected_discovery(self) -> Discovery | None:
        """The currently selected discovery, if any."""
        proxy_index = self.table.currentIndex()
        if not proxy_index.isValid():
            return None
        source_index = self.proxy.mapToSource(proxy_index)
        discovery_id = self.model.data(
            self.model.index(source_index.row(), 0), Qt.UserRole
        )
        return self._discoveries.get(str(discovery_id))

    @property
    def visible_row_count(self) -> int:
        """Rows passing the current filters (for tests and status bars)."""
        return self.proxy.rowCount()

    # -- internal ------------------------------------------------------------

    def _apply_filters(self) -> None:
        self.proxy.provider = self.provider_combo.currentText()
        self.proxy.classification = self.classification_combo.currentText()
        self.proxy.time_range_days = _TIME_RANGE_DAYS[self.time_combo.currentIndex()]
        self.proxy.newly_created_only = self.new_check.isChecked()
        self.proxy.recently_active_only = self.active_check.isChecked()
        self.proxy.min_score = self.min_score_spin.value()
        self.proxy.invalidate()

    def _on_double_click(self, proxy_index: QModelIndex) -> None:
        source_index = self.proxy.mapToSource(proxy_index)
        discovery_id = self.model.data(
            self.model.index(source_index.row(), 0), Qt.UserRole
        )
        discovery = self._discoveries.get(str(discovery_id))
        if discovery is not None:
            self.detail_requested.emit(discovery)
