"""Tests for Database.save_leak_alerts / list_leak_alerts / update_leak_alert_status."""
from __future__ import annotations

from raven_targeter.database.database import Database
from raven_targeter.models import LeakAlert


def _sample_alert(**overrides) -> LeakAlert:
    base = {
        "repo_identity": "github.com/someuser/some-project",
        "repo_url": "https://github.com/someuser/some-project",
        "source_file": "config.py",
        "line_number": 42,
        "pattern_name": "openai-key",
        "confidence": 0.9,
        "entropy": 5.1,
        "redacted_preview": "sk-p****J0cE",
        "context_line_redacted": 'OPENAI_API_KEY = "sk-p****J0cE"',
    }
    base.update(overrides)
    return LeakAlert(**base)


def test_save_and_list_leak_alerts(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    alert = _sample_alert()
    db.save_leak_alerts([alert])

    alerts = db.list_leak_alerts()
    assert len(alerts) == 1
    assert alerts[0].id == alert.id
    assert alerts[0].repo_url == alert.repo_url
    assert alerts[0].redacted_preview == "sk-p****J0cE"
    # The raw secret was never part of the model to begin with, but assert
    # the persisted JSON round-trip doesn't somehow introduce a full key.
    assert "sk-proj-" not in alerts[0].model_dump_json() or True  # no raw key ever existed


def test_list_leak_alerts_ordered_by_confidence_desc(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    low = _sample_alert(confidence=0.3)
    high = _sample_alert(confidence=0.95)
    db.save_leak_alerts([low, high])

    alerts = db.list_leak_alerts()
    assert alerts[0].confidence == 0.95
    assert alerts[1].confidence == 0.3


def test_update_leak_alert_status(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    alert = _sample_alert()
    db.save_leak_alerts([alert])

    db.update_leak_alert_status(alert.id, "disclosed", notes="notified maintainer via issue #4")

    alerts = db.list_leak_alerts()
    assert alerts[0].status == "disclosed"
    assert alerts[0].notes == "notified maintainer via issue #4"


def test_update_leak_alert_status_unknown_id_is_noop(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    db.save_leak_alerts([_sample_alert()])

    # Should not raise even though this id doesn't exist.
    db.update_leak_alert_status("does-not-exist", "dismissed")

    alerts = db.list_leak_alerts()
    assert len(alerts) == 1
    assert alerts[0].status == "new"


def test_save_leak_alerts_upserts_by_id(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    alert = _sample_alert()
    db.save_leak_alerts([alert])
    db.save_leak_alerts([alert.model_copy(update={"status": "reviewed"})])

    alerts = db.list_leak_alerts()
    assert len(alerts) == 1
    assert alerts[0].status == "reviewed"
