"""Leak detection for the responsible-disclosure helper.

Detects that a credential-shaped string exists at a specific public location
(repo/file/line) so a human can go verify and responsibly disclose it. This
module NEVER returns, stores, or logs the matched secret value itself —
only its pattern type, a redacted preview, an entropy-based confidence
score, and location evidence.

Design intent (do not change without re-reading this docstring):
  - `detect_leaks()` is the only public entry point besides the dataclass.
  - The raw matched string exists only inside this function's local scope,
    for the minimum time needed to score it and build a redacted preview.
  - Callers (adapters) must not attempt to recover the raw value from the
    LeakFinding — there is no field that carries it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# (pattern_name, compiled_regex, capture_group_index_for_the_secret)
_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("openai-key", re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b"), 1),
    ("anthropic-key", re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{20,})\b"), 1),
    ("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})\b"), 1),
    ("aws-access-key-id", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), 1),
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
    confidence: float  # 0.0-1.0
    entropy: float
    redacted_preview: str  # e.g. "sk-ab12****wxyz" — never enough to reconstruct
    line_number: int
    context_line_redacted: str  # the surrounding line, secret portion redacted
    matched_length: int
    source_file: str | None = None
    suppressed_reason: str | None = None  # set only on findings deliberately excluded


def _shannon_entropy(s: str) -> float:
    """Shannon entropy in bits/char. Higher = more random-looking = more likely real."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _redacted_preview(secret: str) -> str:
    """A short preview that reveals prefix/suffix shape but not the working value.

    Keeps at most 4 chars at each end, replaces the middle with a fixed-length
    mask so the mask itself doesn't leak the true length.
    """
    if len(secret) <= 10:
        return secret[:2] + "****"
    return f"{secret[:4]}****{secret[-4:]}"


def _looks_like_placeholder(line: str) -> bool:
    low = line.lower()
    return any(word in low for word in _SUPPRESS_CONTEXT_WORDS)


def _confidence(secret: str, entropy: float, suppressed: bool) -> float:
    if suppressed:
        return 0.05
    # Entropy for genuine API keys (base62/base64-ish charsets) typically
    # lands ~4.0-4.8 bits/char. Low-entropy strings (repeated chars, obvious
    # words) score low regardless of pattern match.
    entropy_component = min(entropy / 4.5, 1.0)
    length_component = min(len(secret) / 40, 1.0)
    score = 0.5 * entropy_component + 0.3 + 0.2 * length_component
    return round(min(max(score, 0.0), 0.99), 2)


def detect_leaks(text: str, *, source_file: str | None = None) -> list[LeakFinding]:
    """Scan text for credential-shaped strings. Returns findings, never secrets.

    Suppressed (placeholder-context) matches are included with low confidence
    and a `suppressed_reason` set, rather than silently dropped, so a caller
    can choose to filter them but auditors can see what was considered.
    """
    findings: list[LeakFinding] = []
    lines = text.splitlines()

    for line_no, line in enumerate(lines, start=1):
        placeholder_context = _looks_like_placeholder(line)

        # Collect every secret matched anywhere on this line first, so the
        # context snippet redacts ALL of them — not just the one belonging
        # to the current finding. Otherwise a second secret on the same
        # line as the first match leaks in cleartext into context_line_redacted.
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
            findings.append(
                LeakFinding(
                    pattern_name=pattern_name,
                    confidence=confidence,
                    entropy=round(entropy, 2),
                    redacted_preview=_redacted_preview(secret),
                    line_number=line_no,
                    context_line_redacted=redacted_line,
                    matched_length=len(secret),
                    source_file=source_file,
                    suppressed_reason=(
                        "placeholder-context" if placeholder_context else None
                    ),
                )
            )
    return findings


def high_confidence_findings(
    findings: list[LeakFinding], *, threshold: float = 0.6
) -> list[LeakFinding]:
    """Filter to findings likely worth a human's attention."""
    return [f for f in findings if f.suppressed_reason is None and f.confidence >= threshold]
