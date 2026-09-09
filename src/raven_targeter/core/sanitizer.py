"""Credential redaction and API-implementation-pattern detection.

Public GitHub text (READMEs, code, issues) sometimes contains strings that
resemble secrets — example keys, leaked tokens, or auth headers. Raven is a
*discovery* tool: it must redact anything credential-like before storing or
displaying fetched text, and it must never persist harvested secrets, even
redacted-looking ones.

Two responsibilities live here:

1. :func:`redact_text` — replace credential-like substrings with
   ``[REDACTED_*]`` placeholders.
2. :func:`detect_api_patterns` / :func:`find_matched_terms` — identify API
   *implementation* signals (endpoint definitions, client code) that feed
   the scorer. Detecting an implementation is not harvesting a credential.
"""

from __future__ import annotations

import re

REDACTED_KEY = "[REDACTED_API_KEY]"
REDACTED_TOKEN = "[REDACTED_TOKEN]"

# Ordered (pattern, replacement). Order matters: specific key formats first,
# generic assignments last.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenAI-style keys (sk-...) and project keys (sk-proj-...).
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9\-_]{8,}"), REDACTED_KEY),
    # Anthropic keys.
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{8,}"), REDACTED_KEY),
    # GitHub tokens: classic, fine-grained, OAuth, server-to-server.
    (
        re.compile(
            r"(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{8,}"
        ),
        REDACTED_TOKEN,
    ),
    # Slack tokens.
    (re.compile(r"xox[bpas]-[A-Za-z0-9\-_]{8,}"), REDACTED_TOKEN),
    # AWS access key IDs.
    (re.compile(r"AKIA[0-9A-Z]{16}"), REDACTED_TOKEN),
    # Bearer tokens in headers / code.
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/=]{8,}"), "Bearer " + REDACTED_TOKEN),
    # Generic api_key / apikey assignments with a plausible secret value.
    (
        re.compile(
            r"(?i)\b(api[_-]?key|x-api-key)\b\s*[:=]\s*['\"]?([\w\-.~+/=]{12,})['\"]?"
        ),
        r"\1=[REDACTED_API_KEY]",
    ),
)

# Signals that fetched text actually implements/consumes an AI API, per the
# product manifest (section 11). Used for scoring, not for secret storage.
API_IMPLEMENTATION_PATTERNS: tuple[str, ...] = (
    "/api/",
    "/v1/",
    "authorization",
    "bearer",
    "api_key",
    "x-api-key",
    "requests.post",
    "httpx",
    "fetch(",
    "axios",
    "fastapi",
    "flask",
    "express.router",
    "openai(",
    "anthropic(",
    "generativelanguage.googleapis.com",
    "api.openai.com",
    "api.anthropic.com",
)


def redact_text(text: str) -> str:
    """Replace credential-like substrings with ``[REDACTED_*]`` placeholders.

    The transformation is one-way: the original secret value is dropped, so
    redacted text is safe to store, display, and export.
    """
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def contains_secret(text: str) -> bool:
    """True if text contains anything credential-like (pre-redaction check)."""
    return any(pattern.search(text) is not None for pattern, _ in _SECRET_PATTERNS)


def detect_api_patterns(text: str) -> list[str]:
    """Return the API implementation patterns found in text.

    Matching is case-insensitive. Results are sorted for determinism and
    feed the scorer's implementation-evidence component.
    """
    lowered = text.lower()
    return sorted({p for p in API_IMPLEMENTATION_PATTERNS if p in lowered})


def find_matched_terms(text: str, candidate_terms: list[str]) -> list[str]:
    """Return candidate terms appearing in text (case-insensitive).

    Used to record *why* a discovery matched: provider names, intent
    keywords, or user-supplied keywords. Results are deduplicated and
    sorted for determinism.
    """
    lowered = text.lower()
    matched = {
        term for term in candidate_terms if term.strip() and term.lower() in lowered
    }
    return sorted(matched)
