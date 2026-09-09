"""Structured logging configuration for Raven-Targeter.

All timestamps are UTC. Log level is configurable via Settings.log_level.
Never log secret values (e.g. GITHUB_TOKEN) — callers must redact before
passing sensitive strings into log messages.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime


class UTCFormatter(logging.Formatter):
    """Formatter that renders record timestamps in UTC, ISO-8601."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=UTC)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="seconds")


_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once. Safe to call multiple times."""
    global _CONFIGURED

    root = logging.getLogger()
    root.setLevel(level)

    if _CONFIGURED:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = UTCFormatter(
        fmt="%(asctime)sZ [%(levelname)s] %(name)s: %(message)s",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger. Call configure_logging() first."""
    return logging.getLogger(name)
