"""Versioned Raven discovery export consumed by Raven-Validator."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from raven_targeter.models import Discovery

SCHEMA = "raven-discovery-export-v1"


def interchange_record(d: Discovery) -> dict[str, object]:
    return {
        "title": d.title,
        "source_url": d.url,
        "source": d.source,
        "source_type": d.source_type,
        "provider": d.provider,
        "classification": d.classification,
        "score": d.total_score,
        "evidence": d.evidence,
        "candidate_endpoints": [ep.model_dump(mode="json") for ep in d.candidate_endpoints],
    }


def export_json(discoveries: list[Discovery], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": SCHEMA, "discoveries": [interchange_record(d) for d in discoveries]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def export_csv(discoveries: list[Discovery], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["title", "source_url", "source_type", "provider", "classification", "score", "candidate_endpoints", "evidence"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for d in discoveries:
            w.writerow({
                "title": d.title,
                "source_url": d.url,
                "source_type": d.source_type,
                "provider": d.provider or "",
                "classification": d.classification,
                "score": d.total_score,
                "candidate_endpoints": json.dumps([ep.model_dump(mode="json") for ep in d.candidate_endpoints], ensure_ascii=False),
                "evidence": " | ".join(d.evidence),
            })
    return path
