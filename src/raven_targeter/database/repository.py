"""Repository pattern over the SQLite store.

The GUI and services talk to :class:`RavenRepository`, never to sessions
or ORM objects directly. Reads return detached data (Pydantic models and
a small :class:`RunSummary` dataclass), so callers can use results after
the session closes — important for Qt worker threads.

Datetime note: SQLite drops tzinfo, so every timestamp read back is
re-attached to UTC by :func:`_aware` before leaving this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, desc, select
from sqlalchemy.orm import sessionmaker

from raven_targeter.adapters.base import SearchError
from raven_targeter.database.models import (
    DiscoveryRecord,
    Evidence,
    SearchErrorRecord,
    SearchRun,
)
from raven_targeter.models import Discovery
from raven_targeter.utils.dates import now_utc


@dataclass(frozen=True)
class RunSummary:
    """Detached, GUI-safe view of one search run."""

    id: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    lookback_days: int
    targets: list[str]
    sources: list[str]
    candidate_count: int
    accepted_count: int
    error_count: int


def _aware(value: datetime | None) -> datetime | None:
    """Re-attach UTC to naive datetimes coming back from SQLite."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _dumps(items: list[str]) -> str:
    return json.dumps(items)


def _loads(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _record_to_discovery(
    record: DiscoveryRecord, evidence_contents: list[str]
) -> Discovery:
    return Discovery(
        id=record.id,
        source=record.source,
        source_type=record.source_type,  # type: ignore[arg-type]
        provider=record.provider,
        title=record.title,
        url=record.url,
        author=record.author,
        created_at=_aware(record.created_at),
        updated_at=_aware(record.updated_at),
        pushed_at=_aware(record.pushed_at),
        discovered_at=_aware(record.discovered_at) or now_utc(),
        description=record.description,
        stars=record.stars,
        forks=record.forks,
        matched_terms=_loads(record.matched_terms_json),
        evidence=evidence_contents,
        relevance_score=record.relevance_score,
        freshness_score=record.freshness_score,
        implementation_score=record.implementation_score,
        engagement_score=record.engagement_score,
        confidence_score=record.confidence_score,
        classification=record.classification,  # type: ignore[arg-type]
        canonical_url=record.canonical_url,
        repo_identity=record.repo_identity,
    )


def _run_to_summary(run: SearchRun) -> RunSummary:
    started = _aware(run.started_at)
    assert started is not None
    return RunSummary(
        id=run.id,
        started_at=started,
        completed_at=_aware(run.completed_at),
        status=run.status,
        lookback_days=run.lookback_days,
        targets=_loads(run.targets_json),
        sources=_loads(run.sources_json),
        candidate_count=run.candidate_count,
        accepted_count=run.accepted_count,
        error_count=run.error_count,
    )


class RavenRepository:
    """Synchronous persistence facade. One instance per engine."""

    def __init__(self, engine: Engine) -> None:
        self._factory = sessionmaker(bind=engine, expire_on_commit=False)

    # -- runs ------------------------------------------------------------

    def create_run(
        self,
        lookback_days: int,
        targets: list[str],
        sources: list[str],
    ) -> str:
        """Insert a new running search run; return its ID."""
        run_id = uuid4().hex
        with self._factory() as session:
            session.add(
                SearchRun(
                    id=run_id,
                    started_at=now_utc(),
                    status="running",
                    lookback_days=lookback_days,
                    targets_json=_dumps(targets),
                    sources_json=_dumps(sources),
                )
            )
            session.commit()
        return run_id

    def complete_run(
        self,
        run_id: str,
        *,
        candidate_count: int,
        accepted_count: int,
        error_count: int,
        status: str = "completed",
    ) -> None:
        """Stamp completion counts on a run.

        Raises:
            KeyError: If no run with the ID exists.
        """
        with self._factory() as session:
            run = session.get(SearchRun, run_id)
            if run is None:
                raise KeyError(f"Unknown search run: {run_id}")
            run.completed_at = now_utc()
            run.status = status
            run.candidate_count = candidate_count
            run.accepted_count = accepted_count
            run.error_count = error_count
            session.commit()

    def get_run(self, run_id: str) -> RunSummary | None:
        """Return a detached summary, or None if the run does not exist."""
        with self._factory() as session:
            run = session.get(SearchRun, run_id)
            return _run_to_summary(run) if run is not None else None

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        """Newest-first run summaries."""
        with self._factory() as session:
            rows = session.scalars(
                select(SearchRun).order_by(desc(SearchRun.started_at)).limit(limit)
            ).all()
            return [_run_to_summary(run) for run in rows]

    # -- discoveries ------------------------------------------------------

    def save_discoveries(
        self, run_id: str, discoveries: list[Discovery]
    ) -> int:
        """Persist discoveries (and their evidence rows). Returns rows saved."""
        if not discoveries:
            return 0
        with self._factory() as session:
            for discovery in discoveries:
                record = DiscoveryRecord(
                    id=discovery.id,
                    search_run_id=run_id,
                    source=discovery.source,
                    source_type=discovery.source_type,
                    provider=discovery.provider,
                    title=discovery.title,
                    url=discovery.url,
                    author=discovery.author,
                    created_at=discovery.created_at,
                    updated_at=discovery.updated_at,
                    pushed_at=discovery.pushed_at,
                    discovered_at=discovery.discovered_at,
                    description=discovery.description,
                    stars=discovery.stars,
                    forks=discovery.forks,
                    matched_terms_json=_dumps(discovery.matched_terms),
                    relevance_score=discovery.relevance_score,
                    freshness_score=discovery.freshness_score,
                    implementation_score=discovery.implementation_score,
                    engagement_score=discovery.engagement_score,
                    confidence_score=discovery.confidence_score,
                    total_score=discovery.total_score,
                    classification=discovery.classification,
                    canonical_url=discovery.canonical_url,
                    repo_identity=discovery.repo_identity,
                )
                session.add(record)
                for position, content in enumerate(discovery.evidence):
                    session.add(
                        Evidence(
                            discovery_id=discovery.id,
                            source=discovery.source,
                            evidence_type=f"text-{position}",
                            content=content,
                        )
                    )
            session.commit()
        return len(discoveries)

    def get_discoveries(
        self,
        run_id: str,
        *,
        provider: str | None = None,
        classification: str | None = None,
        min_score: float = 0.0,
        limit: int = 500,
    ) -> list[Discovery]:
        """Discoveries for a run, highest total score first, with filters."""
        with self._factory() as session:
            stmt = (
                select(DiscoveryRecord)
                .where(DiscoveryRecord.search_run_id == run_id)
                .order_by(desc(DiscoveryRecord.total_score))
                .limit(limit)
            )
            if provider is not None:
                stmt = stmt.where(DiscoveryRecord.provider == provider)
            if classification is not None:
                stmt = stmt.where(DiscoveryRecord.classification == classification)
            if min_score > 0:
                stmt = stmt.where(DiscoveryRecord.total_score >= min_score)
            records = session.scalars(stmt).all()
            result: list[Discovery] = []
            for record in records:
                contents = session.scalars(
                    select(Evidence.content)
                    .where(Evidence.discovery_id == record.id)
                    .order_by(Evidence.id)
                ).all()
                result.append(_record_to_discovery(record, list(contents)))
            return result

    def get_discovery(self, discovery_id: str) -> Discovery | None:
        """One discovery by ID, or None."""
        with self._factory() as session:
            record = session.get(DiscoveryRecord, discovery_id)
            if record is None:
                return None
            contents = session.scalars(
                select(Evidence.content)
                .where(Evidence.discovery_id == record.id)
                .order_by(Evidence.id)
            ).all()
            return _record_to_discovery(record, list(contents))

    def count_discoveries(self, run_id: str) -> int:
        """Number of stored discoveries for a run."""
        with self._factory() as session:
            rows = session.scalars(
                select(DiscoveryRecord.id).where(
                    DiscoveryRecord.search_run_id == run_id
                )
            ).all()
            return len(rows)

    # -- errors ------------------------------------------------------------

    def save_errors(self, run_id: str, errors: list[SearchError]) -> int:
        """Persist explicit adapter errors. Returns rows saved."""
        if not errors:
            return 0
        with self._factory() as session:
            for error in errors:
                session.add(
                    SearchErrorRecord(
                        search_run_id=run_id,
                        source=error.source,
                        status_code=error.status_code,
                        message=error.message,
                        retryable=error.retryable,
                        occurred_at=error.occurred_at,
                    )
                )
            session.commit()
        return len(errors)

    def get_errors(self, run_id: str) -> list[SearchError]:
        """Errors for a run in recorded order."""
        with self._factory() as session:
            rows = session.scalars(
                select(SearchErrorRecord)
                .where(SearchErrorRecord.search_run_id == run_id)
                .order_by(SearchErrorRecord.id)
            ).all()
            return [
                SearchError(
                    source=row.source,
                    status_code=row.status_code,
                    message=row.message,
                    retryable=row.retryable,
                    occurred_at=_aware(row.occurred_at) or now_utc(),
                )
                for row in rows
            ]
