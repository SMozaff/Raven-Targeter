"""GitHub Gist adapter — documented placeholder, disabled by default.

GitHub exposes no full-text Gist search API equivalent to repository /
code / issue search, so real Gist discovery cannot be built on the GitHub
API alone in V1. This class exists so the adapter registry, settings, and
GUI source toggles have a stable extension point, and so the reason for
its disabled state is recorded in code, not just in docs.

Full Gist discovery is deferred to the future web-search layer
(e.g. ``site:gist.github.com`` queries), which is explicitly out of scope
for V1. This adapter must not fake Gist search: while disabled, its
``search()`` returns no discoveries and a single explicit error saying so.
"""

from __future__ import annotations

from raven_targeter.adapters.base import (
    AdapterSearchResult,
    SearchAdapter,
    SearchError,
)
from raven_targeter.models import QueryVariant

DISABLED_MESSAGE = (
    "GitHubGistAdapter is disabled by default: GitHub provides no full-text "
    "Gist search API, so V1 performs no Gist discovery. Real Gist coverage "
    "is deferred to the future web-search layer."
)


class GitHubGistAdapter(SearchAdapter):
    """Placeholder Gist adapter. Disabled; never fabricates results."""

    name = "github_gists"
    enabled = False

    async def search(
        self,
        queries: list[QueryVariant],
        max_results: int = 200,
    ) -> AdapterSearchResult:
        """Return zero discoveries plus an explicit disabled-state error."""
        return AdapterSearchResult(
            discoveries=[],
            errors=[
                SearchError(
                    source="github_gists",
                    message=DISABLED_MESSAGE,
                    retryable=False,
                )
            ],
        )

    async def aclose(self) -> None:
        """No network resources to release."""
        return None
