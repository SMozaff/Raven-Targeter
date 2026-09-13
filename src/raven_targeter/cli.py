"""Headless entry point: raven-hunter scan ..."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from raven_targeter.config.settings import DEFAULT_TARGETS, get_settings
from raven_targeter.models import SearchRequest
from raven_targeter.services.hunter_export import export_csv, export_json
from raven_targeter.services.hunter_service import hunt


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="raven-hunter",
        description="Headless credential exposure scanner for public GitHub repositories",
    )
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""),
                   help="GitHub personal access token (or $GITHUB_TOKEN)")
    p.add_argument("--targets", default=",".join(DEFAULT_TARGETS),
                   help="Comma-separated target families")
    p.add_argument("--keywords", default="", help="Comma-separated extra keywords")
    p.add_argument("--lookback", type=int, default=10, help="Lookback window in days")
    p.add_argument("--max-results", type=int, default=200, help="Max discoveries")
    p.add_argument("--verify", action="store_true",
                   help="Send discovered credentials to provider APIs for verification")
    p.add_argument("--output", default="raven-hunter-report.json", help="Output path")
    p.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    p.add_argument("--quiet", action="store_true", help="Suppress progress output")
    return p


async def _run(args: argparse.Namespace) -> int:
    if not args.token.strip():
        print("[error] GitHub token required (--token or $GITHUB_TOKEN)", file=sys.stderr)
        return 2

    settings = get_settings()
    targets = [t.strip().lower() for t in args.targets.split(",") if t.strip()]
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    request = SearchRequest(
        targets=targets,
        keywords=keywords,
        lookback_days=args.lookback,
        max_results_per_source=args.max_results,
        sources=["repository", "code", "issue", "pull_request"],
        web_search=False,
    )

    if not args.quiet:
        print(
            f"[run] targets={targets} lookback={args.lookback}d "
            f"max={args.max_results} verify={args.verify}",
            file=sys.stderr,
        )

    report = await hunt(
        request,
        settings,
        github_token=args.token,
        verify=args.verify,
    )

    output_path = Path(args.output)
    if args.format == "csv":
        export_csv(report, output_path)
    else:
        export_json(report, output_path)

    if not args.quiet:
        print(
            f"[done] discoveries={report.metrics.discoveries} "
            f"alerts={report.metrics.leak_alerts} "
            f"valid={report.metrics.valid_credentials} "
            f"→ {output_path}",
            file=sys.stderr,
        )

    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())