"""GitHub adapter → LeakAlert integration tests."""
from __future__ import annotations

import pytest

from raven_targeter.adapters.github import GitHubAdapter
from raven_targeter.models import Discovery


def _make_discovery() -> Discovery:
    return Discovery(
        source_type="repository",
        title="owner/repo",
        url="https://github.com/owner/repo",
        repo_identity="github.com/owner/repo",
    )


@pytest.mark.asyncio
async def test_readme_enrichment_generates_leak_alert():
    adapter = GitHubAdapter(token="dummy")
    discovery = _make_discovery()
    raw = "OPENAI_API_KEY=sk-proj-abc123DEF456ghi789JKL012mno345PQR678stu901VWX234yzAbcDeF"
    alerts = await adapter._build_leak_alerts(
        raw, discovery=discovery, source_file="README"
    )
    assert len(alerts) == 1
    assert alerts[0].pattern_name.startswith("openai")
    assert alerts[0].verification is None  # no verify_callback set
    await adapter.aclose()


@pytest.mark.asyncio
async def test_clean_readme_generates_no_alerts():
    adapter = GitHubAdapter(token="dummy")
    discovery = _make_discovery()
    raw = "This is a normal README paragraph with no credentials."
    alerts = await adapter._build_leak_alerts(
        raw, discovery=discovery, source_file="README"
    )
    assert alerts == []
    await adapter.aclose()


@pytest.mark.asyncio
async def test_placeholder_key_is_filtered():
    adapter = GitHubAdapter(token="dummy")
    discovery = _make_discovery()
    raw = "OPENAI_API_KEY=sk-proj-xxxxx  # example placeholder"
    alerts = await adapter._build_leak_alerts(
        raw, discovery=discovery, source_file="README"
    )
    # Placeholder context suppresses and filters below 0.6
    assert alerts == []
    await adapter.aclose()


@pytest.mark.asyncio
async def test_verify_callback_populates_outcome():
    from raven_targeter.models import VerifyOutcome

    async def fake_verify(pattern_name: str, token: str) -> VerifyOutcome:
        return VerifyOutcome(kind="valid", detail="test accepted")

    adapter = GitHubAdapter(token="dummy", verify_callback=fake_verify)
    discovery = _make_discovery()
    raw = "OPENAI_API_KEY=sk-proj-abc123DEF456ghi789JKL012mno345PQR678stu901VWX234yzAbcDeF"
    alerts = await adapter._build_leak_alerts(
        raw, discovery=discovery, source_file="README"
    )
    assert len(alerts) == 1
    assert alerts[0].verification is not None
    assert alerts[0].verification.kind == "valid"
    await adapter.aclose()