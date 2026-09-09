"""JSON/CSV export of normalized discoveries.

Export logic lives here — never inside GUI widgets. Callers (the main
window, tests, future CLI) pass plain :class:`Discovery` lists and get
back the written file path. Files land in ``<exports_dir>/YYYY-MM-DD/``
with a UTC timestamped name, so repeated exports never collide.

Only normalized fields are exported — never raw provider payloads, and
(consistent with the rest of the app) never the user's ``GITHUB_TOKEN``,
which appears in no model this module touches.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from raven_targeter.models import Discovery
from raven_targeter.utils.dates import now_utc

EXPORT_FORMATS = ("json", "csv")

# Flattened CSV columns. Lists join with "; " to keep one row per discovery.
EXPORT_COLUMNS: tuple[str, ...] = (
    "id",
    "source",
    "source_type",
    "provider",
    "title",
    "url",
    "author",
    "created_at",
    "updated_at",
    "pushed_at",
    "discovered_at",
    "description",
    "stars",
    "forks",
    "classification",
    "relevance_score",
    "freshness_score",
    "implementation_score",
    "engagement_score",
    "confidence_score",
    "total_score",
    "matched_terms",
    "evidence",
)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def flatten_discovery(discovery: Discovery) -> dict[str, str]:
    """Flatten one discovery to string cells for CSV export."""
    return {
        "id": discovery.id,
        "source": discovery.source,
        "source_type": discovery.source_type,
        "provider": discovery.provider or "",
        "title": discovery.title,
        "url": discovery.url,
        "author": discovery.author or "",
        "created_at": _iso(discovery.created_at),
        "updated_at": _iso(discovery.updated_at),
        "pushed_at": _iso(discovery.pushed_at),
        "discovered_at": _iso(discovery.discovered_at),
        "description": discovery.description or "",
        "stars": "" if discovery.stars is None else str(discovery.stars),
        "forks": "" if discovery.forks is None else str(discovery.forks),
        "classification": discovery.classification,
        "relevance_score": f"{discovery.relevance_score:.1f}",
        "freshness_score": f"{discovery.freshness_score:.1f}",
        "implementation_score": f"{discovery.implementation_score:.1f}",
        "engagement_score": f"{discovery.engagement_score:.1f}",
        "confidence_score": f"{discovery.confidence_score:.1f}",
        "total_score": f"{discovery.total_score:.1f}",
        "matched_terms": "; ".join(discovery.matched_terms),
        "evidence": " | ".join(discovery.evidence),
    }


def _dated_dir(exports_dir: str | Path) -> Path:
    """``<exports_dir>/YYYY-MM-DD`` (UTC), created on demand."""
    directory = Path(exports_dir) / now_utc().strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _stamp() -> str:
    return now_utc().strftime("%Y%m%d-%H%M%S")


def export_json(discoveries: list[Discovery], exports_dir: str | Path) -> Path:
    """Write normalized discoveries as a JSON array. Returns the file path."""
    path = _dated_dir(exports_dir) / f"raven-{_stamp()}.json"
    payload = [d.model_dump(mode="json") for d in discoveries]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


def export_csv(discoveries: list[Discovery], exports_dir: str | Path) -> Path:
    """Write flattened discoveries as CSV (headers always written)."""
    path = _dated_dir(exports_dir) / f"raven-{_stamp()}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPORT_COLUMNS))
        writer.writeheader()
        for discovery in discoveries:
            writer.writerow(flatten_discovery(discovery))
    return path


def export_discoveries(
    discoveries: list[Discovery],
    exports_dir: str | Path,
    format: str = "json",
) -> Path:
    """Export in ``"json"`` or ``"csv"`` format. Returns the file path.

    Raises:
        ValueError: For an unknown format name.
    """
    if format == "json":
        return export_json(discoveries, exports_dir)
    if format == "csv":
        return export_csv(discoveries, exports_dir)
    raise ValueError(
        f"Unknown export format: {format!r} (expected one of {EXPORT_FORMATS})"
    )
