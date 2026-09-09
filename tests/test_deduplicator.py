"""Tests for core/deduplicator.py."""

from __future__ import annotations

from raven_targeter.core.deduplicator import (
    attach_repo_identity,
    deduplicate,
    merge_group,
    merge_key,
)
from raven_targeter.models import Discovery


def _repo(url: str, **kwargs: object) -> Discovery:
    base: dict[str, object] = {
        "title": "repo",
        "url": url,
        "source_type": "repository",
        "canonical_url": "",
    }
    base.update(kwargs)
    data = dict(base)
    return Discovery(**data)  # type: ignore[arg-type]


def test_same_repo_different_sources_merges():
    a = _repo(
        "https://github.com/foo/bar",
        matched_terms=["claude"],
        evidence=["repo hit"],
        relevance_score=40.0,
    )
    b = _repo(
        "https://github.com/Foo/Bar/",
        source_type="code",
        matched_terms=["wrapper"],
        evidence=["code hit"],
        relevance_score=70.0,
    )
    merged, removed = deduplicate([a, b])
    assert removed == 1
    assert len(merged) == 1
    assert set(merged[0].matched_terms) == {"claude", "wrapper"}
    assert "repo hit" in merged[0].evidence
    assert "code hit" in merged[0].evidence
    # Scores take the per-component maximum — merging never lowers a score.
    assert merged[0].relevance_score == 70.0
    # Provenance note records the merge.
    assert any("Merged 1 duplicate" in e for e in merged[0].evidence)


def test_distinct_issue_urls_stay_separate():
    repo = _repo("https://github.com/foo/bar")
    issue1 = _repo("https://github.com/foo/bar/issues/1", source_type="issue")
    issue2 = _repo("https://github.com/foo/bar/issues/2", source_type="issue")
    merged, removed = deduplicate([repo, issue1, issue2])
    assert removed == 0
    assert len(merged) == 3


def test_merge_key_case_insensitive():
    a = _repo("https://github.com/Foo/Bar")
    b = _repo("https://github.com/foo/bar")
    assert merge_key(a) == merge_key(b)


def test_merge_group_no_duplicates_returns_primary():
    a = _repo("https://github.com/foo/bar", relevance_score=33.0)
    assert merge_group(a, []) is a


def test_deduplicate_empty():
    merged, removed = deduplicate([])
    assert merged == []
    assert removed == 0


def test_attach_repo_identity():
    d = _repo("https://github.com/foo/bar/issues/7", source_type="issue")
    linked = attach_repo_identity(d, "Foo", "Bar")
    assert linked.repo_identity == "github.com/foo/bar"
    assert linked.url == d.url
