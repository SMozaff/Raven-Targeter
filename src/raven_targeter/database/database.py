"""Minimal SQLAlchemy persistence for search results and leak alerts."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from raven_targeter.models import Discovery, LeakAlert


class Base(DeclarativeBase):
    pass


class DiscoveryRow(Base):
    __tablename__ = "discoveries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    payload_json: Mapped[str] = mapped_column(Text)


class LeakAlertRow(Base):
    """A responsible-disclosure alert: location + confidence, never the secret."""

    __tablename__ = "leak_alerts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    discovery_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    repo_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repo_url: Mapped[str] = mapped_column(Text)
    source_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_number: Mapped[int] = mapped_column(Integer)
    pattern_name: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="new")
    payload_json: Mapped[str] = mapped_column(Text)


class Database:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url)
        Base.metadata.create_all(self.engine)

    def save(self, discoveries: list[Discovery]) -> None:
        with Session(self.engine) as s:
            for d in discoveries:
                s.merge(DiscoveryRow(
                    id=d.id, provider=d.provider, source_type=d.source_type, title=d.title,
                    url=d.url, score=d.total_score, payload_json=d.model_dump_json(),
                ))
            s.commit()

    def list(self) -> list[Discovery]:
        with Session(self.engine) as s:
            rows = s.scalars(select(DiscoveryRow).order_by(DiscoveryRow.score.desc())).all()
            return [Discovery(**json.loads(r.payload_json)) for r in rows]

    def save_leak_alerts(self, alerts: list[LeakAlert]) -> None:
        """Persist alerts. Never call with anything containing a raw secret —
        LeakAlert's schema makes that structurally impossible upstream, but
        this is the boundary where it would land in the database if it did."""
        with Session(self.engine) as s:
            for a in alerts:
                s.merge(LeakAlertRow(
                    id=a.id, discovery_id=a.discovery_id, repo_identity=a.repo_identity,
                    repo_url=a.repo_url, source_file=a.source_file, line_number=a.line_number,
                    pattern_name=a.pattern_name, confidence=a.confidence, status=a.status,
                    payload_json=a.model_dump_json(),
                ))
            s.commit()

    def list_leak_alerts(self) -> list[LeakAlert]:
        with Session(self.engine) as s:
            rows = s.scalars(
                select(LeakAlertRow).order_by(LeakAlertRow.confidence.desc())
            ).all()
            return [LeakAlert(**json.loads(r.payload_json)) for r in rows]

    def update_leak_alert_status(self, alert_id: str, status: str, notes: str | None = None) -> None:
        with Session(self.engine) as s:
            row = s.get(LeakAlertRow, alert_id)
            if row is None:
                return
            alert = LeakAlert(**json.loads(row.payload_json))
            alert = alert.model_copy(update={"status": status, "notes": notes})
            row.status = status
            row.payload_json = alert.model_dump_json()
            s.commit()
