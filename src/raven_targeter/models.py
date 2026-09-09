"""Normalized Pydantic models shared by the search pipeline, GUI, and export.

Every discovery — regardless of which adapter produced it — normalizes into
a :class:`Discovery`. The GUI and export layers must only depend on these
models, never on provider-specific (GitHub) JSON shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from raven_targeter.config.settings import DEFAULT_TARGETS
from raven_targeter.config.targets import normalize_target
from raven_targeter.utils.dates import ensure_utc, now_utc

SearchType = Literal["repository", "code", "issue", "pull_request"]

SourceType = Literal["repository", "code", "issue", "pull_request"]

Classification = Literal[
    "api-wrapper",
    "sdk",
    "proxy",
    "gateway",
    "client",
    "openai-compatible",
    "example",
    "automation",
    "discussion",
    "unknown",
]

CLASSIFICATIONS: tuple[str, ...] = (
    "api-wrapper",
    "sdk",
    "proxy",
    "gateway",
    "client",
    "openai-compatible",
    "example",
    "automation",
    "discussion",
    "unknown",
)


def _validate_utc(value: datetime | None) -> datetime | None:
    """Pydantic-compatible validator: reject naive/non-UTC datetimes."""
    if value is None:
        return None
    return ensure_utc(value)


class QueryVariant(BaseModel):
    """One focused search query for a single target and search type.

    `query_text` holds the keyword portion of the GitHub `q` parameter
    (e.g. `"claude" wrapper`). `qualifiers` holds structured GitHub search
    qualifiers (e.g. `{"created": ">=2026-08-30"}`) that the adapter merges
    into the `q` parameter via httpx `params={...}` — never by URL string
    concatenation.
    """

    model_config = {"frozen": True}

    target: str
    search_type: SearchType
    query_text: str
    qualifiers: dict[str, str] = Field(default_factory=dict)

    @field_validator("target", mode="before")
    @classmethod
    def _normalize_target(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_target(value)
        return value

    @property
    def dedup_key(self) -> tuple[str, str, str]:
        """Stable key for query deduplication."""
        qualifier_key = "&".join(f"{k}={v}" for k, v in sorted(self.qualifiers.items()))
        return (self.target, self.search_type, f"{self.query_text} {qualifier_key}".strip())


class SearchRequest(BaseModel):
    """Validated parameters for one search run."""

    model_config = {"frozen": True}

    targets: list[str] = Field(default_factory=lambda: list(DEFAULT_TARGETS))
    keywords: list[str] = Field(default_factory=list)
    lookback_days: int = Field(default=10, ge=1, le=365)
    sources: list[str] = Field(
        default_factory=lambda: ["repository", "code", "issue", "pull_request"]
    )
    max_results_per_source: int = Field(default=200, ge=1, le=1000)
    minimum_score: float = Field(default=0.0, ge=0.0, le=100.0)

    @field_validator("targets", mode="before")
    @classmethod
    def _normalize_targets(cls, value: object) -> object:
        if isinstance(value, str):
            items = [t.strip() for t in value.split(",")]
        elif isinstance(value, (list, tuple)):
            items = [str(t).strip() for t in value]
        else:
            return value
        return [normalize_target(t) for t in items if t]

    @field_validator("keywords", mode="before")
    @classmethod
    def _clean_keywords(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return [str(k).strip() for k in value if str(k).strip()]
        return value


class Discovery(BaseModel):
    """One normalized discovery from a real GitHub API response."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    source: str = Field(default="github")
    source_type: SourceType = Field(default="repository")
    provider: str | None = Field(default=None)
    title: str
    url: str
    author: str | None = Field(default=None)

    created_at: datetime | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)
    pushed_at: datetime | None = Field(default=None)
    discovered_at: datetime = Field(default_factory=now_utc)

    description: str | None = Field(default=None)

    stars: int | None = Field(default=None)
    forks: int | None = Field(default=None)

    matched_terms: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    relevance_score: float = Field(default=0.0, ge=0.0, le=100.0)
    freshness_score: float = Field(default=0.0, ge=0.0, le=100.0)
    implementation_score: float = Field(default=0.0, ge=0.0, le=100.0)
    engagement_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=100.0)

    classification: Classification = Field(default="unknown")

    canonical_url: str = Field(default="")
    repo_identity: str | None = Field(default=None)

    _validate_created = field_validator("created_at", mode="before")(_validate_utc)
    _validate_updated = field_validator("updated_at", mode="before")(_validate_utc)
    _validate_pushed = field_validator("pushed_at", mode="before")(_validate_utc)
    _validate_discovered = field_validator("discovered_at", mode="before")(_validate_utc)

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        if isinstance(value, str) and value.strip():
            return normalize_target(value)
        return value

    @property
    def total_score(self) -> float:
        """Weighted total score (weights live in core/scorer.py)."""
        from raven_targeter.core.scorer import SCORING_WEIGHTS, combine_scores

        return combine_scores(
            relevance=self.relevance_score,
            freshness=self.freshness_score,
            implementation_evidence=self.implementation_score,
            engagement=self.engagement_score,
            confidence=self.confidence_score,
            weights=SCORING_WEIGHTS,
        )
