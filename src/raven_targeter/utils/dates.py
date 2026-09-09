"""UTC date helpers."""
from datetime import UTC, datetime, timedelta


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Naive datetime is not allowed")
    return value.astimezone(UTC)


def cutoff_utc(days: int, reference: datetime | None = None) -> datetime:
    ref = ensure_utc(reference) if reference is not None else now_utc()
    return ref - timedelta(days=days)


def parse_github_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
