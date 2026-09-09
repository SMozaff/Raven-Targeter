"""Tests for core/date_validator.py: created-vs-pushed classification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from raven_targeter.core.date_validator import classify_repo_dates, filter_recent
from raven_targeter.models import Discovery


def _ref() -> datetime:
    return datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)


def test_newly_created_only():
    ref = _ref()
    status = classify_repo_dates(
        created_at=ref - timedelta(days=2),
        pushed_at=ref - timedelta(days=60),
        lookback_days=10,
        reference=ref,
    )
    assert status.newly_created is True
    assert status.recently_active is False
    assert status.is_recent is True
    assert status.date_source == "github.created_at"
    assert status.date_confidence == 1.0


def test_recently_active_only():
    ref = _ref()
    status = classify_repo_dates(
        created_at=ref - timedelta(days=200),
        pushed_at=ref - timedelta(days=1),
        lookback_days=10,
        reference=ref,
    )
    assert status.newly_created is False
    assert status.recently_active is True
    assert status.date_source == "github.pushed_at"


def test_both_axes():
    ref = _ref()
    status = classify_repo_dates(
        created_at=ref - timedelta(days=2),
        pushed_at=ref - timedelta(days=1),
        lookback_days=10,
        reference=ref,
    )
    assert status.newly_created is True
    assert status.recently_active is True
    assert status.date_source == "github.created_at"


def test_neither_axis():
    ref = _ref()
    status = classify_repo_dates(
        created_at=ref - timedelta(days=200),
        pushed_at=ref - timedelta(days=60),
        lookback_days=10,
        reference=ref,
    )
    assert status.is_recent is False
    assert status.date_source == "none"
    assert status.date_confidence == 0.0


def test_unknown_dates_never_recent():
    status = classify_repo_dates(None, None, 10, reference=_ref())
    assert status.is_recent is False


def test_updated_at_fallback_when_pushed_missing():
    ref = _ref()
    status = classify_repo_dates(
        created_at=ref - timedelta(days=200),
        pushed_at=None,
        lookback_days=10,
        updated_at=ref - timedelta(days=3),
        reference=ref,
    )
    assert status.recently_active is True
    assert status.date_source == "github.updated_at"


def test_exact_cutoff_boundary_is_inclusive():
    ref = _ref()
    status = classify_repo_dates(
        created_at=ref - timedelta(days=10),
        pushed_at=None,
        lookback_days=10,
        reference=ref,
    )
    assert status.newly_created is True


def test_naive_datetimes_rejected():
    with pytest.raises(ValueError):
        classify_repo_dates(
            created_at=datetime(2026, 1, 1),
            pushed_at=None,
            lookback_days=10,
            reference=_ref(),
        )


def test_filter_recent_keeps_only_recent():
    ref = _ref()
    recent = Discovery(
        title="recent",
        url="https://github.com/a/b",
        created_at=ref - timedelta(days=1),
    )
    stale = Discovery(
        title="stale",
        url="https://github.com/c/d",
        created_at=ref - timedelta(days=100),
        pushed_at=ref - timedelta(days=100),
    )
    unknown = Discovery(title="unknown", url="https://github.com/e/f")
    kept = filter_recent([recent, stale, unknown], 10, reference=ref)
    assert kept == [recent]
