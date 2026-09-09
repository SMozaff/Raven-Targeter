"""UTC date helpers shared across the core pipeline.

All datetimes in Raven-Targeter are timezone-aware and normalized to UTC.
Naive datetimes are treated as a bug and rejected rather than silently
assumed to be UTC, since that assumption has bitten date-filtering logic
in similar tools before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def now_utc() -> datetime:
    """Current time, timezone-aware, UTC."""
    return datetime.now(UTC)


def cutoff_utc(lookback_days: int, *, reference: datetime | None = None) -> datetime:
    """Compute the UTC cutoff for a given lookback window.

    Args:
        lookback_days: Number of days to look back. Must be >= 1.
        reference: Optional reference "now" (UTC-aware). Defaults to now_utc().

    Returns:
        The UTC datetime before which candidates are considered stale.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    ref = reference if reference is not None else now_utc()
    ensure_utc(ref)
    return ref - timedelta(days=lookback_days)


def ensure_utc(dt: datetime) -> datetime:
    """Validate that a datetime is timezone-aware and in UTC. Raises otherwise."""
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime not allowed: {dt!r}")
    if dt.utcoffset() != timedelta(0):
        raise ValueError(f"Datetime must be UTC, got offset {dt.utcoffset()!r}: {dt!r}")
    return dt


def parse_github_timestamp(value: str | None) -> datetime | None:
    """Parse a GitHub API timestamp string (ISO-8601, 'Z' suffix) to UTC datetime.

    Returns None if value is None or empty. Raises ValueError on malformed input.
    """
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_within_lookback(
    dt: datetime | None, lookback_days: int, *, reference: datetime | None = None
) -> bool:
    """True if dt is timezone-aware, UTC, and >= the computed cutoff.

    A None dt is always considered outside the lookback window (unknown dates
    must never be silently treated as recent).
    """
    if dt is None:
        return False
    ensure_utc(dt)
    return dt >= cutoff_utc(lookback_days, reference=reference)
