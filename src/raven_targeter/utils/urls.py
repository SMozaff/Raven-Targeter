"""URL canonicalization used for deduplication.

Two URLs pointing at "the same thing" (case differences, trailing slash,
tracking query params, http vs https) should canonicalize to the same
string so the deduplicator can merge them.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Query params that carry no identity information and should be stripped.
_NOISE_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_",
    "source",
}


def canonicalize_url(url: str) -> str:
    """Return a normalized form of `url` suitable for equality-based dedup.

    Normalization applied:
    - lowercase scheme and host
    - force https scheme (github.com always supports it)
    - strip trailing slash from path (except root)
    - drop known tracking query params, sort remaining ones
    - drop URL fragment
    """
    parsed = urlparse(url.strip())
    scheme = "https"
    netloc = parsed.netloc.lower()
    # GitHub org/repo/user segments are case-insensitive, so lowercase the
    # path for dedup purposes. This is GitHub-specific; if this canonicalizer
    # is ever reused for case-sensitive hosts, revisit this.
    path = parsed.path.rstrip("/").lower() or "/"

    raw_params = parse_qsl(parsed.query, keep_blank_values=True)
    kept_params = sorted((k, v) for k, v in raw_params if k.lower() not in _NOISE_PARAMS)
    query = urlencode(kept_params)

    return urlunparse((scheme, netloc, path, "", query, ""))


def canonical_repo_identity(owner: str, repo: str) -> str:
    """Canonical identity string for a GitHub repository, case-insensitive."""
    return f"github.com/{owner.strip().lower()}/{repo.strip().lower()}"
