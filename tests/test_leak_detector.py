"""Tests for core/leak_detector.py.

The one invariant every test here protects: the raw matched secret must
never appear in any LeakFinding field.
"""
from __future__ import annotations

from raven_targeter.core.leak_detector import (
    LeakFinding,
    detect_leaks,
    high_confidence_findings,
)

# Fake, obviously-not-real values used only to exercise the regexes.
_FAKE_OPENAI_KEY = "sk-proj-" + "aB3xY9zQ7mK2wR8tL5vN1pS6dF4hJ0cE"
_FAKE_ANTHROPIC_KEY = "sk-ant-" + "aB3xY9zQ7mK2wR8tL5vN1pS6dF4hJ0cE"
_FAKE_GITHUB_TOKEN = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
_FAKE_AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"


def _assert_no_raw_leak(findings: list[LeakFinding], *raw_secrets: str) -> None:
    for finding in findings:
        for field_name in ("redacted_preview", "context_line_redacted"):
            value = getattr(finding, field_name)
            for secret in raw_secrets:
                assert secret not in value, f"raw secret leaked into {field_name}: {value!r}"


def test_detects_openai_style_key():
    text = f'OPENAI_API_KEY = "{_FAKE_OPENAI_KEY}"'
    findings = detect_leaks(text, source_file="config.py")
    assert any(f.pattern_name == "openai-key" for f in findings)
    _assert_no_raw_leak(findings, _FAKE_OPENAI_KEY)


def test_detects_anthropic_style_key():
    text = f'ANTHROPIC_API_KEY = "{_FAKE_ANTHROPIC_KEY}"'
    findings = detect_leaks(text, source_file="config.py")
    assert any(f.pattern_name == "anthropic-key" for f in findings)
    _assert_no_raw_leak(findings, _FAKE_ANTHROPIC_KEY)


def test_detects_github_token():
    text = f"GITHUB_TOKEN={_FAKE_GITHUB_TOKEN}"
    findings = detect_leaks(text, source_file=".env")
    assert any(f.pattern_name == "github-token" for f in findings)
    _assert_no_raw_leak(findings, _FAKE_GITHUB_TOKEN)


def test_detects_aws_access_key_id():
    text = f'aws_access_key_id = "{_FAKE_AWS_KEY}"'
    findings = detect_leaks(text, source_file="credentials")
    assert any(f.pattern_name == "aws-access-key-id" for f in findings)
    _assert_no_raw_leak(findings, _FAKE_AWS_KEY)


def test_placeholder_context_is_suppressed():
    text = 'OPENAI_API_KEY = "sk-your_key_here_placeholder_xxxxxxxxxxxx"'
    findings = detect_leaks(text)
    assert findings, "pattern should still match"
    assert all(f.suppressed_reason == "placeholder-context" for f in findings)
    assert all(f.confidence < 0.3 for f in findings)


def test_example_word_in_line_suppresses():
    text = f"# example: {_FAKE_OPENAI_KEY}"
    findings = detect_leaks(text)
    assert all(f.suppressed_reason == "placeholder-context" for f in findings)


def test_low_entropy_repeated_chars_scores_low():
    # Real pattern shape but low-entropy body -> should not be high confidence
    # even without placeholder words, because low entropy is itself a signal.
    low_entropy_secret = "sk-" + "a" * 30
    text = f'key = "{low_entropy_secret}"'
    findings = detect_leaks(text)
    assert findings
    assert all(f.confidence < 0.6 for f in findings)


def test_real_looking_key_scores_high_confidence():
    text = f'OPENAI_API_KEY = "{_FAKE_OPENAI_KEY}"'
    findings = detect_leaks(text)
    high_conf = high_confidence_findings(findings)
    assert len(high_conf) >= 1
    assert high_conf[0].confidence >= 0.6


def test_no_match_on_clean_text():
    text = "def hello():\n    print('hello world')\n"
    findings = detect_leaks(text)
    assert findings == []


def test_line_number_is_correct():
    text = "line one\nline two\nOPENAI_API_KEY = \"" + _FAKE_OPENAI_KEY + '"\nline four'
    findings = detect_leaks(text)
    assert any(f.line_number == 3 for f in findings)


def test_source_file_propagated():
    text = f'OPENAI_API_KEY = "{_FAKE_OPENAI_KEY}"'
    findings = detect_leaks(text, source_file="src/config.py")
    assert findings[0].source_file == "src/config.py"


def test_redacted_preview_never_equals_raw_secret():
    text = f'OPENAI_API_KEY = "{_FAKE_OPENAI_KEY}"'
    findings = detect_leaks(text)
    for f in findings:
        assert f.redacted_preview != _FAKE_OPENAI_KEY
        assert "****" in f.redacted_preview


def test_high_confidence_findings_excludes_suppressed():
    text = (
        f'REAL_KEY = "{_FAKE_OPENAI_KEY}"\n'
        f'EXAMPLE_KEY = "sk-your_key_here_placeholder_padding"\n'
    )
    findings = detect_leaks(text)
    high_conf = high_confidence_findings(findings)
    assert all(f.suppressed_reason is None for f in high_conf)


def test_multiple_findings_on_same_line_both_captured():
    text = f'OPENAI="{_FAKE_OPENAI_KEY}" GITHUB="{_FAKE_GITHUB_TOKEN}"'
    findings = detect_leaks(text)
    patterns_found = {f.pattern_name for f in findings}
    assert "openai-key" in patterns_found
    assert "github-token" in patterns_found
    _assert_no_raw_leak(findings, _FAKE_OPENAI_KEY, _FAKE_GITHUB_TOKEN)
