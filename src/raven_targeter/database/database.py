"""Engine creation and schema initialization for Raven-Targeter storage.

V1 uses SQLite via ``RAVEN_DB_URL`` (default ``sqlite:///data/raven.db``).
The engine factory keeps SQLite pragmas sane (WAL journal mode for
concurrent GUI reads during background writes) and guarantees the parent
directory exists for file-backed URLs.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import Engine, create_engine, event

logger = logging.getLogger(__name__)


def _sqlite_path(db_url: str) -> Path | None:
    """Extract the filesystem path from a ``sqlite:///`` URL, if any."""
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        raw = db_url[len(prefix):]
        if raw and raw != ":memory:":
            return Path(raw)
    return None


def build_engine(db_url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the given database URL."""
    path = _sqlite_path(db_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            db_url,
            echo=echo,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(db_url, echo=echo)


def init_db(engine: Engine) -> None:
    """Create all tables. Safe to call on an existing database."""
    from raven_targeter.database.models import Base

    Base.metadata.create_all(engine)
    logger.info("Database schema initialized")
