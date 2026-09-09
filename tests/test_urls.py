"""Tests for utils/urls.py."""

from __future__ import annotations

from raven_targeter.utils.urls import canonical_repo_identity, canonicalize_url


def test_canonicalize_scheme_normalized_to_https():
    assert canonicalize_url("http://github.com/foo/bar") == "https://github.com/foo/bar"


def test_canonicalize_host_case_insensitive():
    assert canonicalize_url("https://GitHub.com/foo/bar") == "https://github.com/foo/bar"


def test_canonicalize_path_case_insensitive():
    assert canonicalize_url("https://github.com/Foo/Bar") == "https://github.com/foo/bar"


def test_canonicalize_trailing_slash_stripped():
    assert canonicalize_url("https://github.com/foo/bar/") == "https://github.com/foo/bar"


def test_canonicalize_root_path_preserved():
    assert canonicalize_url("https://github.com") == "https://github.com/"
    assert canonicalize_url("https://github.com/") == "https://github.com/"


def test_canonicalize_strips_tracking_params():
    a = canonicalize_url("https://github.com/foo/bar?utm_source=x&utm_campaign=y")
    b = canonicalize_url("https://github.com/foo/bar")
    assert a == b


def test_canonicalize_keeps_meaningful_query_params():
    a = canonicalize_url("https://github.com/foo/bar?tab=readme")
    assert "tab=readme" in a


def test_canonicalize_strips_fragment():
    a = canonicalize_url("https://github.com/foo/bar#readme")
    b = canonicalize_url("https://github.com/foo/bar")
    assert a == b


def test_canonicalize_sorts_multiple_query_params():
    a = canonicalize_url("https://github.com/foo/bar?b=2&a=1")
    b = canonicalize_url("https://github.com/foo/bar?a=1&b=2")
    assert a == b


def test_canonical_repo_identity_case_insensitive():
    assert canonical_repo_identity("Foo", "Bar") == canonical_repo_identity("foo", "bar")


def test_canonical_repo_identity_format():
    assert canonical_repo_identity("openai", "openai-python") == "github.com/openai/openai-python"
