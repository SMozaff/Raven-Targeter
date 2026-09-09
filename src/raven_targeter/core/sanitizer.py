"""Redact credential-like values before evidence is stored/exported."""
from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,})\b"),
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[=:]\s*)[^\s\"']+"),
]


def redact_text(text: str) -> str:
    out = text
    for pattern in _PATTERNS:
        if pattern.groups >= 1 and "authorization" in pattern.pattern.lower():
            out = pattern.sub(r"\1[REDACTED]", out)
        elif pattern.groups >= 1 and "key|token" in pattern.pattern.lower():
            out = pattern.sub(r"\1[REDACTED]", out)
        else:
            out = pattern.sub("[REDACTED]", out)
    return out


def find_matched_terms(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    return list(dict.fromkeys(t for t in terms if t and t.lower() in low))
