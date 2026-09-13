"""One-shot discovery + verification pipeline.

Runs the standard search, then — if ``verify=True`` — dispatches each
high-confidence leak alert through the provider verifier. The raw secret
never leaves the ``GitHubAdapter`` scan loop; the verifier receives it
directly from the adapter's callback.
"""
from __future__ import annotations

from raven_targeter.adapters.github import GitHubAdapter
from raven_targeter.adapters.serpapi import SerpAPIAdapter
from raven_targeter.config.settings import Settings
from raven_targeter.core.verifier import verify_by_pattern
from raven_targeter.models import (
    HunterMetrics,
    HunterReport,
    LeakAlert,
    SearchRequest,
    VerifiedCredential,
    VerifyOutcome,
)
from raven_targeter.services.search_service import SearchPipeline
from raven_targeter.utils.dates import now_utc

_PROVIDER_PREFIXES = (
    "openai", "anthropic", "github", "google", "slack", "stripe",
    "sendgrid", "twilio", "huggingface", "deepseek", "aws",
)


def _verify_callback(enabled: bool):
    """Return an async callback that verifies one (pattern, token) pair.

    Passing ``None`` to the adapter disables verification entirely.
    """
    if not enabled:
        return None

    async def cb(pattern_name: str, token: str) -> VerifyOutcome:
        return await verify_by_pattern(pattern_name, token)

    return cb


def _build_verified_credentials(alerts: list[LeakAlert]) -> list[VerifiedCredential]:
    out: list[VerifiedCredential] = []
    for alert in alerts:
        if alert.verification is None:
            continue
        if alert.verification.kind != "valid":
            continue
        provider = None
        name = alert.pattern_name.lower()
        for p in _PROVIDER_PREFIXES:
            if name.startswith(p):
                provider = p
                break
        out.append(
            VerifiedCredential(
                alert_id=alert.id,
                provider=provider or "unknown",
                repo_url=alert.repo_url,
                repo_identity=alert.repo_identity,
                source_file=alert.source_file,
                line_number=alert.line_number,
                pattern_name=alert.pattern_name,
                redacted_preview=alert.redacted_preview,
                outcome=alert.verification,
            )
        )
    return out


async def hunt(
    request: SearchRequest,
    settings: Settings,
    *,
    github_token: str | None = None,
    search_api_key: str | None = None,
    search_provider: str = "disabled",
    search_engine: str = "google",
    verify: bool = False,
) -> HunterReport:
    github = None
    web = None
    try:
        if request.sources and github_token:
            github = GitHubAdapter(
                github_token, verify_callback=_verify_callback(verify)
            )
        if request.web_search and search_provider == "serpapi" and search_api_key:
            web = SerpAPIAdapter(
                search_api_key,
                engine=search_engine,
                base_url=settings.search_api_base_url,
                max_queries=settings.search_api_max_queries,
            )
        discoveries, errors, leak_alerts = await SearchPipeline().run(
            request, github, web
        )
    finally:
        if github is not None:
            await github.aclose()
        if web is not None:
            await web.aclose()

    verified = _build_verified_credentials(leak_alerts)

    metrics = HunterMetrics(
        discoveries=len(discoveries),
        leak_alerts=len(leak_alerts),
        alerts_verified=sum(1 for a in leak_alerts if a.verification is not None),
        valid_credentials=sum(
            1 for a in leak_alerts
            if a.verification is not None and a.verification.kind == "valid"
        ),
        invalid_credentials=sum(
            1 for a in leak_alerts
            if a.verification is not None and a.verification.kind == "invalid"
        ),
        unverifiable_credentials=sum(
            1 for a in leak_alerts
            if a.verification is not None and a.verification.kind == "unverifiable"
        ),
    )

    return HunterReport(
        generated_at=now_utc(),
        request=request,
        discoveries=discoveries,
        leak_alerts=leak_alerts,
        verified_credentials=verified,
        errors=errors,
        metrics=metrics,
    )