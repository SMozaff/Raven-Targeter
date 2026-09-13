"""Leak detection for the responsible-disclosure helper.

Detects that a credential-shaped string exists at a specific public location
(repo/file/line) so a human can go verify and responsibly disclose it. This
module NEVER returns, stores, or logs the matched secret value itself in its
public API — only its pattern type, a redacted preview, an entropy-based
confidence score, and location evidence.

``detect_leaks_raw`` is the ONE exception: it returns the raw secret only so
the caller can dispatch it to a provider verifier. The caller is contractually
required not to persist, log, or export that value.

Design intent (do not change without re-reading this docstring):
  - ``detect_leaks()`` is the default public entry point.
  - ``detect_leaks_raw()`` is the verification path.
  - Callers that only need alerts MUST use ``detect_leaks()``.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# (pattern_name, compiled_regex, capture_group_index_for_the_secret)
_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    # OpenAI family
    ("openai-project", re.compile(r"\b(sk-proj-[A-Za-z0-9_\-]{60,})\b"), 1),
    ("openai-svcacct", re.compile(r"\b(sk-svcacct-[A-Za-z0-9_\-]{40,})\b"), 1),
    ("openai-key", re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b"), 1),
    # Anthropic family
    ("anthropic-key-full", re.compile(r"\b(sk-ant-api03-[A-Za-z0-9_\-]{90,})\b"), 1),
    ("anthropic-key", re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{20,})\b"), 1),
    # GitHub family
    ("github-pat-fg", re.compile(r"\b(github_pat_[A-Za-z0-9_]{82})\b"), 1),
    ("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})\b"), 1),
    # AWS
    ("aws-access-key-id", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), 1),
    # Google
    ("google-api-key", re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"), 1),
    # Slack
    ("slack-bot", re.compile(r"\b(xoxb-[A-Za-z0-9\-]{10,})\b"), 1),
    ("slack-user", re.compile(r"\b(xoxp-[A-Za-z0-9\-]{10,})\b"), 1),
    # Stripe
    ("stripe-live", re.compile(r"\b(sk_live_[A-Za-z0-9]{24,})\b"), 1),
    ("stripe-test", re.compile(r"\b(sk_test_[A-Za-z0-9]{24,})\b"), 1),
    # SendGrid
    ("sendgrid-key", re.compile(r"\b(SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43})\b"), 1),
    # Twilio
    ("twilio-key", re.compile(r"\b(SK[0-9a-fA-F]{32})\b"), 1),
    # Hugging Face
    ("huggingface-token", re.compile(r"\b(hf_[A-Za-z0-9]{34,})\b"), 1),
    # Generic
    ("generic-bearer", re.compile(r"(?i)authorization\s*:\s*bearer\s+([A-Za-z0-9._-]{16,})"), 1),
    (
        "generic-assignment",
        re.compile(r"(?i)\b(?:api[_-]?key|secret|token)\s*[=:]\s*[\"']?([A-Za-z0-9_\-./+]{16,})[\"']?"),
        1,
    ),
]

# Lines containing these (case-insensitive) are almost always placeholders,
# fixtures, or documentation, not live secrets.
_SUPPRESS_CONTEXT_WORDS = (
    "example",
    "sample",
    "dummy",
    "placeholder",
    "your_",
    "your-",
    "xxxxxxxx",
    "changeme",
    "insert_",
    "test_key",
    "fake",
    "<your",
    "{your",
)


@dataclass(frozen=True)
class LeakFinding:
    """Evidence that a credential-shaped string was found. Never carries the secret."""

    pattern_name: str
    confidence: float
    entropy: float
    redacted_preview: str
    line_number: int
    context_line_redacted: str
    matched_length: int
    source_file: str | None = None
    suppressed_reason: str | None = None


def _shannon_entropy(s: str) -> float:
    """Shannon entropy in bits/char. Higher = more random-looking = more likely real."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _redacted_preview(secret: str) -> str:
    """A short preview that reveals prefix/suffix shape but not the working value."""
    if len(secret) <= 10:
        return secret[:2] + "****"
    return f"{secret[:4]}****{secret[-4:]}"


def _looks_like_placeholder(line: str) -> bool:
    low = line.lower()
    return any(word in low for word in _SUPPRESS_CONTEXT_WORDS)


def _confidence(secret: str, entropy: float, suppressed: bool) -> float:
    if suppressed:
        return 0.05
    entropy_component = min(entropy / 4.5, 1.0)
    length_component = min(len(secret) / 40, 1.0)
    score = 0.5 * entropy_component + 0.3 + 0.2 * length_component
    return round(min(max(score, 0.0), 0.99), 2)


def _scan_lines(text: str, source_file: str | None):
    """Shared line walker. Yields (finding, raw_secret) tuples."""
    for line_no, line in enumerate(text.splitlines(), start=1):
        placeholder_context = _looks_like_placeholder(line)

        line_secrets: list[str] = []
        per_pattern_matches: list[tuple[str, re.Match[str]]] = []
        for pattern_name, pattern, group_idx in _PATTERNS:
            for match in pattern.finditer(line):
                secret = match.group(group_idx)
                if not secret:
                    continue
                line_secrets.append(secret)
                per_pattern_matches.append((pattern_name, match))

        if not line_secrets:
            continue

        redacted_line = line.strip()[:300]
        for secret in sorted(set(line_secrets), key=len, reverse=True):
            redacted_line = redacted_line.replace(secret, _redacted_preview(secret))

        for pattern_name, match in per_pattern_matches:
            group_idx = next(idx for name, _, idx in _PATTERNS if name == pattern_name)
            secret = match.group(group_idx)
            entropy = _shannon_entropy(secret)
            confidence = _confidence(secret, entropy, placeholder_context)
            finding = LeakFinding(
                pattern_name=pattern_name,
                confidence=confidence,
                entropy=round(entropy, 2),
                redacted_preview=_redacted_preview(secret),
                line_number=line_no,
                context_line_redacted=redacted_line,
                matched_length=len(secret),
                source_file=source_file,
                suppressed_reason=("placeholder-context" if placeholder_context else None),
            )
            yield finding, secret


def detect_leaks(text: str, *, source_file: str | None = None) -> list[LeakFinding]:
    """Scan text for credential-shaped strings. Returns findings, never secrets.

    Suppressed (placeholder-context) matches are included with low confidence
    and a ``suppressed_reason`` set, rather than silently dropped, so a caller
    can choose to filter them but auditors can see what was considered.
    """
    return [finding for finding, _secret in _scan_lines(text, source_file)]


def detect_leaks_raw(
    text: str, *, source_file: str | None = None
) -> list[tuple[LeakFinding, str]]:
    """Like ``detect_leaks``, but also returns the raw secret alongside each finding.

    The raw secret is provided ONLY so the caller can dispatch it to a provider
    verifier. Callers MUST NOT persist, log, or export the second element of
    each tuple.
    """
    return list(_scan_lines(text, source_file))


def high_confidence_findings(
    findings: list[LeakFinding], *, threshold: float = 0.6
) -> list[LeakFinding]:
    """Filter to findings likely worth a human's attention."""
    return [f for f in findings if f.suppressed_reason is None and f.confidence >= threshold]