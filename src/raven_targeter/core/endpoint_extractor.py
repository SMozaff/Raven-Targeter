"""Conservative API endpoint extraction from public project evidence."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from raven_targeter.models import CandidateEndpoint

_URL_RE = re.compile(r"https?://[^\s<>\]\[\)\(\"'`]+", re.IGNORECASE)
_API_HINTS = (
    "/v1", "/api", "/models", "/chat/completions", "/responses", "/messages",
    "api.", "endpoint", "base_url", "api_url", "openapi", "swagger",
)
_SKIP_HOSTS = {"github.com", "raw.githubusercontent.com", "api.github.com", "localhost"}


def _public_host(host: str) -> bool:
    host = host.lower().strip(".")
    if not host or host in _SKIP_HOSTS or host.endswith(".github.com"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)


def _clean_url(url: str) -> str | None:
    url = url.rstrip(".,;:!?}")
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    if p.scheme not in {"http", "https"} or not p.hostname or not _public_host(p.hostname):
        return None
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, ""))


def _kind(url: str) -> tuple[str, float]:
    low = url.lower()
    if "openapi" in low or "swagger" in low:
        return "openapi", 0.90
    if low.endswith("/models"):
        return "model-endpoint", 0.90
    if any(x in low for x in ("/chat/completions", "/responses", "/messages")):
        return "generation-endpoint", 0.95
    if any(x in low for x in ("/health", "/healthz", "/status")):
        return "health", 0.75
    if "/v1" in low or "/api" in low or "api." in low:
        return "api-base", 0.82
    return "unknown", 0.45


def extract_candidate_endpoints(text: str, *, source_file: str | None = None) -> list[CandidateEndpoint]:
    """Extract deduplicated public HTTP(S) API-looking URLs with evidence."""
    found: dict[str, CandidateEndpoint] = {}
    for line in text.splitlines():
        line_low = line.lower()
        for match in _URL_RE.findall(line):
            cleaned = _clean_url(match)
            if not cleaned:
                continue
            kind, confidence = _kind(cleaned)
            # A bare site URL is retained only when the surrounding line has
            # an API configuration hint.
            if kind == "unknown" and not any(h in line_low for h in _API_HINTS):
                continue
            ev = line.strip()[:300]
            item = CandidateEndpoint(
                url=cleaned,
                kind=kind,  # type: ignore[arg-type]
                confidence=confidence,
                evidence=ev or f"URL found in {source_file or 'project evidence'}",
                source_file=source_file,
            )
            previous = found.get(cleaned)
            if previous is None or item.confidence > previous.confidence:
                found[cleaned] = item
    return sorted(found.values(), key=lambda x: (-x.confidence, x.url))
