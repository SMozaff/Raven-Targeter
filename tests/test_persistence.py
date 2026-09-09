"""Tests for SQLite persistence — all against a temp file, no real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from raven_targeter.adapters.base import SearchError
from raven_targeter.config.settings import Settings
from raven_targeter.database.database import build_engine, init_db
from raven_targeter.database.repository import RavenRepository
from raven_targeter.models import Discovery


@pytest.fixture
def repo(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path}/test.db")
    init_db(engine)
    repository = RavenRepository(engine)
    yield repository
    engine.dispose()


def _discovery(url: str = "https://github.com/o/r", **overrides) -> Discovery:
    ref = datetime(2026, 9, 9, 12, 0, 0, tzinfo=UTC)
    data = {
        "title": "o/r",
        "url": url,
        "source": "github",
        "source_type": "repository",
        "provider": "openai",
        "author": "o",
        "created_at": ref - timedelta(days=1),
        "updated_at": ref - timedelta(hours=12),
        "pushed_at": ref - timedelta(hours=2),
        "description": "An OpenAI wrapper",
        "stars": 10,
        "forks": 2,
        "matched_terms": ["OpenAI", "wrapper"],
        "evidence": ["Matched repository search", "README excerpt: hello"],
        "relevance_score": 60.0,
        "freshness_score": 80.0,
        "implementation_score": 50.0,
        "engagement_score": 20.0,
        "confidence_score": 70.0,
        "classification": "api-wrapper",
        "canonical_url": "https://github.com/o/r",
        "repo_identity": "github.com/o/r",
    }
    data.update(overrides)
    return Discovery(**data)


def test_empty_store_lists_no_runs(repo):
    assert repo.list_runs() == []


def test_create_and_complete_run(repo):
    run_id = repo.create_run(10, ["openai", "grok"], ["repository", "issue"])
    summary = repo.get_run(run_id)
    assert summary is not None
    assert summary.status == "running"
    assert summary.lookback_days == 10
    assert summary.targets == ["openai", "grok"]
    assert summary.sources == ["repository", "issue"]
    assert summary.completed_at is None
    assert summary.started_at.tzinfo is not None

    repo.complete_run(
        run_id, candidate_count=50, accepted_count=12, error_count=1
    )
    done = repo.get_run(run_id)
    assert done is not None
    assert done.status == "completed"
    assert done.completed_at is not None
    assert done.candidate_count == 50
    assert done.accepted_count == 12
    assert done.error_count == 1


def test_complete_unknown_run_raises(repo):
    with pytest.raises(KeyError):
        repo.complete_run("nope", candidate_count=0, accepted_count=0, error_count=0)


def test_get_run_missing_returns_none(repo):
    assert repo.get_run("nope") is None


def test_save_and_get_discovery_round_trip(repo):
    run_id = repo.create_run(10, ["openai"], ["repository"])
    original = _discovery()
    assert repo.save_discoveries(run_id, [original]) == 1

    fetched = repo.get_discovery(original.id)
    assert fetched is not None
    assert fetched.title == original.title
    assert fetched.url == original.url
    assert fetched.provider == original.provider
    assert fetched.author == original.author
    assert fetched.description == original.description
    assert fetched.stars == 10
    assert fetched.forks == 2
    assert fetched.matched_terms == ["OpenAI", "wrapper"]
    assert fetched.evidence == ["Matched repository search", "README excerpt: hello"]
    assert fetched.classification == "api-wrapper"
    assert fetched.canonical_url == "https://github.com/o/r"
    assert fetched.repo_identity == "github.com/o/r"
    assert fetched.relevance_score == 60.0
    assert fetched.total_score == original.total_score


def test_datetimes_come_back_utc_aware(repo):
    run_id = repo.create_run(10, ["openai"], ["repository"])
    original = _discovery()
    repo.save_discoveries(run_id, [original])

    fetched = repo.get_discovery(original.id)
    assert fetched is not None
    assert fetched.created_at == original.created_at
    assert fetched.pushed_at == original.pushed_at
    assert fetched.discovered_at == original.discovered_at
    for dt in (fetched.created_at, fetched.discovered_at):
        assert dt is not None and dt.tzinfo is not None


def test_get_discoveries_ordered_by_total_score_desc(repo):
    run_id = repo.create_run(10, ["openai"], ["repository"])
    low = _discovery(
        url="https://github.com/o/low",
        canonical_url="https://github.com/o/low",
        relevance_score=0.0,
        freshness_score=0.0,
        implementation_score=0.0,
        engagement_score=0.0,
        confidence_score=0.0,
    )
    high = _discovery(
        url="https://github.com/o/high",
        canonical_url="https://github.com/o/high",
        relevance_score=100.0,
        freshness_score=100.0,
        implementation_score=100.0,
        engagement_score=100.0,
        confidence_score=100.0,
    )
    repo.save_discoveries(run_id, [low, high])
    rows = repo.get_discoveries(run_id)
    assert [r.url for r in rows] == [
        "https://github.com/o/high",
        "https://github.com/o/low",
    ]


def test_get_discoveries_filters(repo):
    run_id = repo.create_run(10, ["openai", "grok"], ["repository"])
    a = _discovery(url="https://github.com/o/a", canonical_url="https://github.com/o/a")
    b = _discovery(
        url="https://github.com/o/b",
        canonical_url="https://github.com/o/b",
        provider="grok",
        classification="proxy",
        relevance_score=100.0,
        freshness_score=100.0,
        implementation_score=100.0,
        engagement_score=100.0,
        confidence_score=100.0,
    )
    repo.save_discoveries(run_id, [a, b])

    assert {r.url for r in repo.get_discoveries(run_id, provider="grok")} == {
        "https://github.com/o/b"
    }
    assert {r.url for r in repo.get_discoveries(run_id, classification="proxy")} == {
        "https://github.com/o/b"
    }
    assert {r.url for r in repo.get_discoveries(run_id, min_score=90.0)} == {
        "https://github.com/o/b"
    }
    assert repo.count_discoveries(run_id) == 2


def test_get_discovery_missing_returns_none(repo):
    assert repo.get_discovery("nope") is None


def test_save_and_get_errors_round_trip(repo):
    run_id = repo.create_run(10, ["openai"], ["repository"])
    errors = [
        SearchError(source="github:repository", status_code=429,
                    message="Too Many Requests", retryable=True),
        SearchError(source="github:readme", status_code=None,
                    message="boom", retryable=False),
    ]
    assert repo.save_errors(run_id, errors) == 2
    fetched = repo.get_errors(run_id)
    assert len(fetched) == 2
    assert fetched[0].status_code == 429
    assert fetched[0].retryable is True
    assert fetched[1].status_code is None
    assert fetched[1].occurred_at.tzinfo is not None


def test_empty_saves_return_zero(repo):
    run_id = repo.create_run(10, ["openai"], ["repository"])
    assert repo.save_discoveries(run_id, []) == 0
    assert repo.save_errors(run_id, []) == 0


def test_github_token_never_stored(tmp_path):
    db_file = tmp_path / "secrets.db"
    engine = build_engine(f"sqlite:///{db_file}")
    init_db(engine)
    repository = RavenRepository(engine)
    try:
        settings = Settings(_env_file=None, github_token="ghp_supersecret999")
        assert settings.has_github_token is True
        run_id = repository.create_run(10, settings.targets, ["repository"])
        repository.save_discoveries(run_id, [_discovery()])
        repository.save_errors(
            run_id,
            [SearchError(source="github:repository", status_code=401,
                         message="Bad credentials", retryable=False)],
        )
        repository.complete_run(
            run_id, candidate_count=1, accepted_count=1, error_count=1
        )
    finally:
        engine.dispose()

    raw = db_file.read_bytes()
    assert b"ghp_supersecret999" not in raw
    for extra in tmp_path.glob("secrets.db*"):
        assert b"ghp_supersecret999" not in extra.read_bytes()


def test_list_runs_newest_first(repo):
    first = repo.create_run(10, ["openai"], ["repository"])
    second = repo.create_run(3, ["grok"], ["issue"])
    ids = [r.id for r in repo.list_runs()]
    assert ids == [second, first]
