"""Normalized models shared by discovery, persistence, GUI, and export."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from raven_targeter.config.settings import DEFAULT_TARGETS
from raven_targeter.utils.dates import ensure_utc, now_utc

SearchType = Literal["repository", "code", "issue", "pull_request", "web"]
Classification = Literal[
    "api-wrapper", "sdk", "proxy", "gateway", "client", "openai-compatible",
    "example", "automation", "discussion", "unknown",
]
EndpointKind = Literal[
    "api-base", "openapi", "health", "model-endpoint", "generation-endpoint", "unknown"
]


class CandidateEndpoint(BaseModel):
    """An HTTP(S) endpoint extracted from public project evidence."""

    url: str
    kind: EndpointKind = "unknown"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: str
    source_file: str | None = None


class QueryVariant(BaseModel):
    model_config = {"frozen": True}
    target: str
    search_type: SearchType
    query_text: str
    qualifiers: dict[str, str] = Field(default_factory=dict)
    freshness_axis: Literal["created", "pushed", "updated", "none"] = "none"

    @property
    def dedup_key(self) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
        return self.target, self.search_type, self.query_text, tuple(sorted(self.qualifiers.items()))


class SearchRequest(BaseModel):
    model_config = {"frozen": True}
    targets: list[str] = Field(default_factory=lambda: list(DEFAULT_TARGETS))
    keywords: list[str] = Field(default_factory=list)
    lookback_days: int = Field(default=10, ge=1, le=365)
    sources: list[str] = Field(default_factory=lambda: ["repository", "code", "issue", "pull_request"])
    web_search: bool = False
    max_results_per_source: int = Field(default=200, ge=1, le=2000)
    max_raw_candidates_per_source: int = Field(default=600, ge=1, le=5000)
    minimum_score: float = Field(default=0.0, ge=0.0, le=100.0)

    @field_validator("targets", mode="before")
    @classmethod
    def normalize_targets(cls, value: object) -> object:
        if isinstance(value, str):
            return [x.strip().lower() for x in value.split(",") if x.strip()]
        if isinstance(value, (list, tuple)):
            return [str(x).strip().lower() for x in value if str(x).strip()]
        return value


class Discovery(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source: str = "github"
    source_type: SearchType = "repository"
    provider: str | None = None
    title: str
    url: str
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    pushed_at: datetime | None = None
    discovered_at: datetime = Field(default_factory=now_utc)
    description: str | None = None
    stars: int | None = None
    forks: int | None = None
    matched_terms: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    candidate_endpoints: list[CandidateEndpoint] = Field(default_factory=list)
    source_path: str | None = None
    relevance_score: float = Field(default=0.0, ge=0.0, le=100.0)
    freshness_score: float = Field(default=0.0, ge=0.0, le=100.0)
    implementation_score: float = Field(default=0.0, ge=0.0, le=100.0)
    engagement_score: float = Field(default=0.0, ge=0.0, le=100.0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=100.0)
    classification: Classification = "unknown"
    canonical_url: str = ""
    repo_identity: str | None = None

    @field_validator("created_at", "updated_at", "pushed_at", "discovered_at", mode="before")
    @classmethod
    def utc_dates(cls, value: datetime | None) -> datetime | None:
        return ensure_utc(value) if value is not None else None

    @property
    def total_score(self) -> float:
        return round(
            self.relevance_score * 0.35
            + self.freshness_score * 0.30
            + self.implementation_score * 0.15
            + self.engagement_score * 0.10
            + self.confidence_score * 0.10,
            2,
        )


class SearchError(BaseModel):
    source: str
    status_code: int | None = None
    message: str
    retryable: bool = False
    occurred_at: datetime = Field(default_factory=now_utc)


class AdapterSearchResult(BaseModel):
    discoveries: list[Discovery] = Field(default_factory=list)
    errors: list[SearchError] = Field(default_factory=list)
