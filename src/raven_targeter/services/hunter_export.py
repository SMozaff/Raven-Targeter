"""Export a HunterReport to JSON or CSV. Never includes raw secrets."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from raven_targeter.models import HunterReport

SCHEMA = "raven-hunter-report-v1"


def export_json(report: HunterReport, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "generated_at": report.generated_at.isoformat(),
        "metrics": report.metrics.model_dump(),
        "discoveries": [d.model_dump(mode="json") for d in report.discoveries],
        "leak_alerts": [a.model_dump(mode="json") for a in report.leak_alerts],
        "verified_credentials": [
            v.model_dump(mode="json") for v in report.verified_credentials
        ],
        "errors": [e.model_dump(mode="json") for e in report.errors],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def export_csv(report: HunterReport, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)

        # Section 1: leak alerts (raw detections, verified or not)
        w.writerow(["# SECTION", "leak_alerts"])
        w.writerow([
            "confidence", "pattern", "preview", "repo", "file", "line",
            "status", "verification_kind", "verification_detail",
        ])
        for a in report.leak_alerts:
            vkind = ""
            vdetail = ""
            if a.verification is not None:
                vkind = a.verification.kind
                vdetail = a.verification.detail or a.verification.reason or ""
            w.writerow([
                f"{a.confidence:.2f}",
                a.pattern_name,
                a.redacted_preview,
                a.repo_identity or a.repo_url,
                a.source_file or "",
                a.line_number,
                a.status,
                vkind,
                _csv_safe(vdetail),
            ])

        # Section 2: verified credentials (only the valid ones)
        w.writerow([])
        w.writerow(["# SECTION", "verified_credentials"])
        w.writerow([
            "provider", "repo", "file", "line", "pattern",
            "preview", "verification_kind", "verification_detail",
        ])
        for v in report.verified_credentials:
            w.writerow([
                v.provider,
                v.repo_identity or v.repo_url,
                v.source_file or "",
                v.line_number,
                v.pattern_name,
                v.redacted_preview,
                v.outcome.kind,
                _csv_safe(v.outcome.detail or v.outcome.reason or ""),
            ])

    return path


def _csv_safe(value: str) -> str:
    if not value:
        return ""
    if value[0] in "=+-@":
        return "'" + value
    return value