"""Raven-Targeter entry point.

Run with:  python app.py
"""

from __future__ import annotations

import sys

from raven_targeter.config.settings import get_settings
from raven_targeter.utils.logging import configure_logging, get_logger


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = get_logger(__name__)

    if not settings.has_github_token:
        logger.warning(
            "No GITHUB_TOKEN configured. GitHub API rate limits will be very low "
            "(60 requests/hour, unauthenticated). Set GITHUB_TOKEN in .env for "
            "higher limits (5000 requests/hour)."
        )

    logger.info(
        "Starting Raven-Targeter | targets=%s lookback_days=%s db_url=%s",
        ",".join(settings.targets),
        settings.lookback_days,
        settings.db_url,
    )

    # PySide6 GUI is wired up in Milestone 4. Until then, this entry point
    # validates config/startup only.
    from raven_targeter.gui.main_window import run_app

    return run_app(settings)


if __name__ == "__main__":
    sys.exit(main())
