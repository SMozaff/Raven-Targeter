"""Tests for utils/dates.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from raven_targeter.utils.dates import (
    cutoff_utc,
    ensure_utc,
    is_within_lookback,
    now_utc,
    parse_github_timestamp,
)


def test_now_utc_is_aware():
    n = now_utc()
    assert n.tzinfo is not None
    assert n.utcoffset() == timedelta(0)


def test_cutoff_utc_basic():
    ref = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    c = cutoff_utc(10, reference=ref)
    assert c == datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def test_cutoff_utc_rejects_invalid_lookback():
    with pytest.raises(ValueError):
        cutoff_utc(0)
    with pytest.raises(ValueError):
        cutoff_utc(-5)


def test_ensure_utc_rejects_naive():
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1))


def test_ensure_utc_rejects_non_utc_offset():
    from datetime import timezone

    tz = timezone(timedelta(hours=5))
    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1, tzinfo=tz))


def test_ensure_utc_accepts_utc():
    dt = datetime(2026, 1, 1, tzinfo=UTC)
    assert ensure_utc(dt) is dt


def test_parse_github_timestamp_z_suffix():
    dt = parse_github_timestamp("2026-09-05T17:00:00Z")
    assert dt == datetime(2026, 9, 5, 17, 0, 0, tzinfo=UTC)


def test_parse_github_timestamp_none_and_empty():
    assert parse_github_timestamp(None) is None
    assert parse_github_timestamp("") is None


def test_parse_github_timestamp_malformed_raises():
    with pytest.raises(ValueError):
        parse_github_timestamp("not-a-date")


def test_is_within_lookback_recent():
    ref = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    recent = ref - timedelta(days=2)
    assert is_within_lookback(recent, 10, reference=ref) is True


def test_is_within_lookback_stale():
    ref = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    stale = ref - timedelta(days=30)
    assert is_within_lookback(stale, 10, reference=ref) is False


def test_is_within_lookback_none_is_always_false():
    """Unknown dates must never be treated as recent (see manifest section 7)."""
    assert is_within_lookback(None, 10) is False


def test_is_within_lookback_rejects_naive():
    with pytest.raises(ValueError):
        is_within_lookback(datetime(2026, 1, 1), 10)


def test_edge_exact_cutoff_boundary_is_inclusive():
    ref = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    exactly_at_cutoff = ref - timedelta(days=10)
    assert is_within_lookback(exactly_at_cutoff, 10, reference=ref) is True
