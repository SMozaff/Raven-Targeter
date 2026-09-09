"""GitHub URL canonicalization."""
from urllib.parse import urlsplit, urlunsplit


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def canonical_repo_identity(owner: str, repo: str) -> str:
    return f"github.com/{owner.strip().lower()}/{repo.strip().lower()}"
