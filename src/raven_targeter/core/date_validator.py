"""Date validation for the search pipeline.

Enforces the lookback window centrally, in UTC. A repository qualifies as:

- ``newly_created`` — ``created_at`` is within the lookback window.
- ``recently_active`` — ``pushed_at`` (or, failing that, ``updated_at``)
  is within the lookback window.
- both — fresh on both axes.

``created_at``, ``updated_at``, and ``pushed_at`` are never conflated:
each is evaluated independently and the result records which date source
qualified the candidate and with what confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raven_targeter.utils.dates import cutoff_utc, ensure_utc


@dataclass(frozen=True)
class RepoDateStatus:
    """Outcome of validating one repository's timestamps."""

    newly_created: bool
    recently_active: bool
    date_source: str
    date_confidence: float

    @property
    def is_recent(self) -> bool:
        """True if the repo qualifies on either axis."""
        return self.newly_created or self.recently_active


def classify_repo_dates(
    created_at: datetime | None,
    pushed_at: datetime | None,
    lookback_days: int,
    updated_at: datetime | None = None,
    reference: datetime | None = None,
) -> RepoDateStatus:
    """Classify a repository's recency along the created/active axes.

    Args:
        created_at: Repository creation timestamp (UTC-aware) or None.
        pushed_at: Last-push timestamp (UTC-aware) or None.
        lookback_days: Search window in days (>= 1).
        updated_at: Last-update timestamp fallback when ``pushed_at`` is
            missing (UTC-aware) or None.
        reference: Optional reference "now" for testing.

    ``date_source`` names the strongest qualifying evidence
    (``"github.created_at"`` beats ``"github.pushed_at"`` beats
    ``"github.updated_at"``); ``"none"`` when nothing qualifies.
    ``date_confidence`` is 1.0 for real GitHub timestamps, 0.0 when no
    usable date exists.
    """
    for dt in (created_at, pushed_at, updated_at):
        if dt is not None:
            ensure_utc(dt)
    cutoff = cutoff_utc(lookback_days, reference=reference)

    newly_created = created_at is not None and created_at >= cutoff
    activity_dt = pushed_at if pushed_at is not None else updated_at
    recently_active = activity_dt is not None and activity_dt >= cutoff

    if newly_created:
        source = "github.created_at"
    elif pushed_at is not None and pushed_at >= cutoff:
        source = "github.pushed_at"
    elif updated_at is not None and updated_at >= cutoff:
        source = "github.updated_at"
    else:
        source = "none"

    confidence = 1.0 if source != "none" else 0.0
    return RepoDateStatus(
        newly_created=newly_created,
        recently_active=recently_active,
        date_source=source,
        date_confidence=confidence,
    )


def filter_recent(
    items: list[object],
    lookback_days: int,
    reference: datetime | None = None,
) -> list[object]:
    """Keep items whose created_at or pushed_at falls in the window.

    Accepts Discovery-like objects exposing ``created_at``/``pushed_at``
    attributes (or mapping keys). Items with unknown dates are dropped —
    they must never be silently treated as recent.
    """

    def _get(item: object, name: str) -> datetime | None:
        if isinstance(item, dict):
            return item.get(name)  # type: ignore[no-any-return]
        return getattr(item, name, None)

    kept: list[object] = []
    for item in items:
        status = classify_repo_dates(
            _get(item, "created_at"),
            _get(item, "pushed_at"),
            lookback_days,
            updated_at=_get(item, "updated_at"),
            reference=reference,
        )
        if status.is_recent:
            kept.append(item)
    return kept
