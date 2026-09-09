"""SQLAlchemy 2.x ORM models for SQLite persistence.

Tables:

- ``search_runs`` — one row per search run with candidate/accepted/error
  counts and a status flag.
- ``discoveries`` — one row per normalized discovery, including all five
  score components plus a ``total_score`` snapshot (computed at save time
  so SQL can filter/sort without reimplementing the weights).
- ``evidence`` — one row per evidence string, linked to its discovery.
- ``search_errors`` — one row per explicit adapter error.

Security rules enforced here: the user's ``GITHUB_TOKEN`` is never
persisted (no column holds it — see ``tests/test_persistence.py``), and
fetched text is expected redacted already (adapters redact before
normalizing; see ``core/sanitizer.py``).

Timezone note: SQLite does not preserve tzinfo, so datetimes read back
from the database are naive. The repository layer re-attaches UTC on
read (see ``repository._aware``); the ORM models store what they are
given, and writers must pass UTC-aware datetimes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all Raven-Targeter ORM models."""


class SearchRun(Base):
    """One search execution with aggregate counts."""

    __tablename__ = "search_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(String(16), default="running")
    lookback_days: Mapped[int] = mapped_column(Integer)
    # JSON-encoded string lists (portable across SQLite/Postgres later).
    targets_json: Mapped[str] = mapped_column(Text, default="[]")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    discoveries: Mapped[list[DiscoveryRecord]] = relationship(
        back_populates="search_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    errors: Mapped[list[SearchErrorRecord]] = relationship(
        back_populates="search_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DiscoveryRecord(Base):
    """One normalized discovery belonging to a search run."""

    __tablename__ = "discoveries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    search_run_id: Mapped[str] = mapped_column(
        ForeignKey("search_runs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="github")
    source_type: Mapped[str] = mapped_column(String(32), default="repository")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    pushed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    matched_terms_json: Mapped[str] = mapped_column(Text, default="[]")

    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    implementation_score: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    total_score: Mapped[float] = mapped_column(Float, default=0.0)

    classification: Mapped[str] = mapped_column(String(32), default="unknown")
    canonical_url: Mapped[str] = mapped_column(Text, default="")
    repo_identity: Mapped[str | None] = mapped_column(
        String(512), nullable=True, default=None
    )

    search_run: Mapped[SearchRun] = relationship(back_populates="discoveries")
    evidence_items: Mapped[list[Evidence]] = relationship(
        back_populates="discovery",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


Index("ix_discoveries_run_score", DiscoveryRecord.search_run_id, DiscoveryRecord.total_score)
Index("ix_discoveries_run_provider", DiscoveryRecord.search_run_id, DiscoveryRecord.provider)


class Evidence(Base):
    """One evidence string attached to a discovery."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discovery_id: Mapped[str] = mapped_column(
        ForeignKey("discoveries.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(32), default="github")
    evidence_type: Mapped[str] = mapped_column(String(32), default="text")
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    discovery: Mapped[DiscoveryRecord] = relationship(back_populates="evidence_items")


class SearchErrorRecord(Base):
    """One explicit adapter error attached to a search run."""

    __tablename__ = "search_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_run_id: Mapped[str] = mapped_column(
        ForeignKey("search_runs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    search_run: Mapped[SearchRun] = relationship(back_populates="errors")
