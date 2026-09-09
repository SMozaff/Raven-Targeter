"""Explicit V1 placeholder: GitHub has no normal full-text Gist search API."""
from raven_targeter.models import AdapterSearchResult, QueryVariant, SearchError


class GitHubGistAdapter:
    enabled = False

    async def search(self, queries: list[QueryVariant], max_results: int = 200) -> AdapterSearchResult:
        del queries, max_results
        return AdapterSearchResult(errors=[SearchError(
            source="github:gists",
            message="Gist full-text discovery is disabled until the web-search layer is added",
            retryable=False,
        )])

    async def aclose(self) -> None:
        return None
