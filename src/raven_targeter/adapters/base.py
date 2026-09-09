"""Adapter contracts for search providers.

Every search provider (GitHub, and later web-search/Reddit/HN adapters)
implements :class:`SearchAdapter`: it takes normalized
:class:`~raven_targeter.models.QueryVariant` objects and returns normalized
:class:`~raven_targeter.models.Discovery` objects plus explicit
:class:`SearchError` records.

HTTP failures are never silently treated as "zero results" — they surface
as `SearchError` with source, status code, message, and retryability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field

from raven_targeter.models import Discovery, QueryVariant
from raven_targeter.utils.dates import now_utc


class SearchError(BaseModel):
    """Explicit, storable record of one failed provider call."""

    model_config = {"frozen": True}

    source: str
    status_code: int | None = Field(default=None)
    message: str = Field(default="")
    retryable: bool = Field(default=False)
    occurred_at: datetime = Field(default_factory=now_utc)


class AdapterSearchResult(BaseModel):
    """Outcome of one adapter search call: hits plus explicit errors."""

    model_config = {"frozen": True}

    discoveries: list[Discovery] = Field(default_factory=list)
    errors: list[SearchError] = Field(default_factory=list)


class SearchAdapter(ABC):
    """Contract all search providers must satisfy."""

    name: str = "base"
    enabled: bool = True

    @abstractmethod
    async def search(
        self,
        queries: list[QueryVariant],
        max_results: int = 200,
    ) -> AdapterSearchResult:
        """Run queries against the provider; return hits and explicit errors."""
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        """Release underlying network resources."""
        raise NotImplementedError
