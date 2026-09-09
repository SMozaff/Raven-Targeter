"""Tests for core/sanitizer.py: redaction and pattern detection."""

from __future__ import annotations

from raven_targeter.core.sanitizer import (
    REDACTED_KEY,
    contains_secret,
    detect_api_patterns,
    find_matched_terms,
    redact_text,
)


def test_redact_openai_key():
    text = "key = 'sk-abc123XYZ4567890'"
    redacted = redact_text(text)
    assert "sk-abc123XYZ4567890" not in redacted
    assert REDACTED_KEY in redacted


def test_redact_anthropic_key():
    text = "ANTHROPIC_API_KEY=sk-ant-abcdef1234567890"
    redacted = redact_text(text)
    assert "sk-ant-abcdef1234567890" not in redacted
    assert REDACTED_KEY in redacted


def test_redact_github_token():
    text = "token ghp_abcdefghij1234567890 leaked"
    redacted = redact_text(text)
    assert "ghp_abcdefghij1234567890" not in redacted


def test_redact_bearer_token():
    text = "Authorization: Bearer abcdef1234567890XYZ"
    redacted = redact_text(text)
    assert "abcdef1234567890XYZ" not in redacted


def test_redact_generic_api_key_assignment():
    text = 'api_key = "supersecretvalue12345"'
    redacted = redact_text(text)
    assert "supersecretvalue12345" not in redacted


def test_redact_preserves_benign_text():
    text = "A Claude wrapper using FastAPI and httpx."
    assert redact_text(text) == text


def test_contains_secret():
    assert contains_secret("sk-abc123XYZ4567890") is True
    assert contains_secret("nothing sensitive here") is False


def test_detect_api_patterns_sorted_deterministic():
    patterns = detect_api_patterns("FastAPI app with HTTPX client calling /v1/chat")
    assert patterns == sorted(patterns)
    assert "fastapi" in patterns
    assert "httpx" in patterns
    assert "/v1/" in patterns


def test_detect_api_patterns_case_insensitive():
    assert "flask" in detect_api_patterns("Built with FLASK")


def test_detect_api_patterns_empty():
    assert detect_api_patterns("a generic blog post about AI news") == []


def test_find_matched_terms():
    matched = find_matched_terms(
        "Claude WRAPPER with proxy support", ["claude", "wrapper", "sdk"]
    )
    assert matched == ["claude", "wrapper"]


def test_find_matched_terms_dedupes_and_sorts():
    matched = find_matched_terms("claude Claude CLAUDE", ["claude", "claude"])
    assert matched == ["claude"]
