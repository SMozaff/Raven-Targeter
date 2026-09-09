"""Tests for export: normalized JSON/CSV output plus GUI wiring."""

from __future__ import annotations

import csv
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from raven_targeter.config.settings import Settings
from raven_targeter.database.database import build_engine, init_db
from raven_targeter.database.repository import RavenRepository
from raven_targeter.gui.main_window import MainWindow
from raven_targeter.gui.results_page import ResultsPage
from raven_targeter.models import Discovery
from raven_targeter.services.export_service import (
    EXPORT_COLUMNS,
    export_csv,
    export_discoveries,
    export_json,
    flatten_discovery,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _discovery(url: str = "https://github.com/o/r", **overrides) -> Discovery:
    ref = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    data = {
        "title": 'A "quoted", comma title',
        "url": url,
        "source": "github",
        "source_type": "repository",
        "provider": "openai",
        "author": "someone",
        "created_at": ref - timedelta(days=1),
        "pushed_at": ref - timedelta(hours=2),
        "description": "Line one.\nLine two.",
        "stars": 7,
        "forks": None,
        "matched_terms": ["OpenAI", "wrapper"],
        "evidence": ["Matched search", "README excerpt"],
        "relevance_score": 60.0,
        "freshness_score": 80.0,
        "implementation_score": 50.0,
        "engagement_score": 20.0,
        "confidence_score": 70.0,
        "classification": "api-wrapper",
        "canonical_url": url,
        "repo_identity": "github.com/o/r",
    }
    data.update(overrides)
    return Discovery(**data)


def test_export_json_normalized_array(tmp_path):
    items = [_discovery(), _discovery("https://github.com/o/s")]
    path = export_json(items, tmp_path)
    assert path.suffix == ".json"
    assert path.parent.parent == tmp_path  # dated subdirectory
    payload = json.loads(path.read_text())
    assert len(payload) == 2
    first = payload[0]
    assert first["title"] == 'A "quoted", comma title'
    assert first["provider"] == "openai"
    assert first["classification"] == "api-wrapper"
    assert first["forks"] is None
    assert "total_score" not in first  # computed property, not a field
    assert "GITHUB_TOKEN" not in path.read_text()


def test_export_json_empty_list(tmp_path):
    path = export_json([], tmp_path)
    assert json.loads(path.read_text()) == []


def test_export_csv_headers_and_quoting(tmp_path):
    path = export_csv([_discovery()], tmp_path)
    assert path.suffix == ".csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0].keys()) == list(EXPORT_COLUMNS)
    assert rows[0]["title"] == 'A "quoted", comma title'  # round-trips
    assert rows[0]["forks"] == ""  # None flattens to empty
    assert rows[0]["stars"] == "7"
    assert rows[0]["matched_terms"] == "OpenAI; wrapper"
    assert "Matched search | README excerpt" in rows[0]["evidence"]
    assert float(rows[0]["total_score"]) > 0


def test_export_csv_empty_list_writes_headers_only(tmp_path):
    path = export_csv([], tmp_path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows == [list(EXPORT_COLUMNS)]


def test_export_discoveries_dispatch_and_rejection(tmp_path):
    assert export_discoveries([_discovery()], tmp_path, "json").suffix == ".json"
    assert export_discoveries([_discovery()], tmp_path, "csv").suffix == ".csv"
    with pytest.raises(ValueError):
        export_discoveries([_discovery()], tmp_path, "xml")


def test_flatten_discovery_cells_are_strings():
    flat = flatten_discovery(_discovery())
    assert all(isinstance(value, str) for value in flat.values())
    assert set(flat) == set(EXPORT_COLUMNS)


# -- GUI wiring ---------------------------------------------------------------


def test_results_export_buttons_emit_format(qapp):
    page = ResultsPage()
    try:
        emitted: list[str] = []
        page.export_requested.connect(emitted.append)
        page.export_json_button.click()
        page.export_csv_button.click()
        assert emitted == ["json", "csv"]
    finally:
        page.close()


def test_visible_discoveries_respects_filters(qapp):
    page = ResultsPage()
    try:
        page.set_discoveries(
            [
                _discovery("https://github.com/o/a"),
                _discovery("https://github.com/o/b", provider="grok"),
            ]
        )
        assert len(page.visible_discoveries()) == 2
        page.provider_combo.setCurrentText("grok")
        visible = page.visible_discoveries()
        assert [d.url for d in visible] == ["https://github.com/o/b"]
    finally:
        page.close()


def test_main_window_export_single_writes_file(qapp, tmp_path):
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    repository = RavenRepository(engine)
    window = MainWindow(
        Settings(_env_file=None), repository, exports_dir=tmp_path
    )
    try:
        window._on_export_single(_discovery())
        files = list(tmp_path.rglob("raven-*.json"))
        assert len(files) == 1
        assert "Exported 1 result" in window.statusBar().currentMessage()
    finally:
        window.close()
        engine.dispose()


def test_main_window_export_visible_writes_csv(qapp, tmp_path):
    engine = build_engine("sqlite:///:memory:")
    init_db(engine)
    repository = RavenRepository(engine)
    window = MainWindow(
        Settings(_env_file=None), repository, exports_dir=tmp_path
    )
    try:
        window.results_page.set_discoveries(
            [_discovery("https://github.com/o/a"), _discovery("https://github.com/o/b")]
        )
        window._on_export_visible("csv")
        files = list(tmp_path.rglob("raven-*.csv"))
        assert len(files) == 1
        with files[0].open(newline="", encoding="utf-8") as handle:
            assert len(list(csv.DictReader(handle))) == 2
        assert "Exported 2 result(s)" in window.statusBar().currentMessage()
    finally:
        window.close()
        engine.dispose()
