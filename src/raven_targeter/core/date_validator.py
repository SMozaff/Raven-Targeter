"""Central recency validation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raven_targeter.utils.dates import cutoff_utc


@dataclass(frozen=True)
class Recency:
    newly_created: bool
    recently_active: bool

    @property
    def is_recent(self) -> bool:
        return self.newly_created or self.recently_active


def classify_dates(created_at: datetime | None, pushed_at: datetime | None, updated_at: datetime | None, days: int) -> Recency:
    cutoff = cutoff_utc(days)
    created = bool(created_at and created_at >= cutoff)
    active_dt = pushed_at or updated_at
    active = bool(active_dt and active_dt >= cutoff)
    return Recency(created, active)
