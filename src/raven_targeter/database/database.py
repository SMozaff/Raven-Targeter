"""Minimal SQLAlchemy persistence for search results."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Float, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from raven_targeter.models import Discovery


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
