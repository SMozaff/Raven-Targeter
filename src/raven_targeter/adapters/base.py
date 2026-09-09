"""Search adapter contract."""
from typing import Protocol

from raven_targeter.models import AdapterSearchResult, QueryVariant


class SearchAdapter(Protocol):
    async def search(self, queries: list[QueryVariant], max_results: int = 200) -> AdapterSearchResult: ...
    async def aclose(self) -> None: ...
