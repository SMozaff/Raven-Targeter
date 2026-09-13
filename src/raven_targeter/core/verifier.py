"""Provider credential verifiers.

Each ``verify_*`` function takes a raw token string and returns a
``VerifyOutcome``. The raw token is used for exactly one HTTP request and is
never stored, logged, or attached to any persistent model.
"""
from __future__ import annotations

import httpx

from raven_targeter.models import VerifyOutcome

_TIMEOUT = 15.0
_UA = {"User-Agent": "Raven-Targeter/0.3"}


def _outcome(status_code: int, provider: str) -> VerifyOutcome:
    if 200 <= status_code < 300:
        return VerifyOutcome(
            kind="valid",
            detail=f"{provider} accepted the credential (HTTP {status_code})",
        )
    if status_code in (401, 403):
        return VerifyOutcome(
            kind="invalid",
            detail=f"{provider} rejected the credential (HTTP {status_code})",
        )
    return VerifyOutcome(
        kind="unverifiable",
        reason=f"{provider} returned HTTP {status_code}; validity undetermined",
    )


async def verify_openai(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
    return _outcome(r.status_code, "OpenAI")


async def verify_anthropic(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "."}],
            },
        )
    return _outcome(r.status_code, "Anthropic")


async def verify_github(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}"},
        )
    return _outcome(r.status_code, "GitHub")


async def verify_google(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://generativelanguage.googleapis.com/v1/models",
            params={"key": token},
        )
    return _outcome(r.status_code, "Google")


async def verify_slack(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
        )
    return _outcome(r.status_code, "Slack")


async def verify_stripe(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://api.stripe.com/v1/charges",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
    return _outcome(r.status_code, "Stripe")


async def verify_sendgrid(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://api.sendgrid.com/v3/scopes",
            headers={"Authorization": f"Bearer {token}"},
        )
    return _outcome(r.status_code, "SendGrid")


async def verify_twilio(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://api.twilio.com/2010-04-01/Accounts.json",
            headers={"Authorization": f"Bearer {token}"},
        )
    return _outcome(r.status_code, "Twilio")


async def verify_huggingface(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}"},
        )
    return _outcome(r.status_code, "HuggingFace")


async def verify_deepseek(token: str) -> VerifyOutcome:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as c:
        r = await c.get(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": f"Bearer {token}"},
        )
    return _outcome(r.status_code, "DeepSeek")


async def verify_aws(_token: str) -> VerifyOutcome:
    """AWS requires a paired access key + secret. A single key cannot be verified."""
    return VerifyOutcome(
        kind="unverifiable",
        reason="AWS requires paired access key + secret; single-key verification not supported",
    )


_PROVIDER_DISPATCH = {
    "openai": verify_openai,
    "anthropic": verify_anthropic,
    "github": verify_github,
    "google": verify_google,
    "slack": verify_slack,
    "stripe": verify_stripe,
    "sendgrid": verify_sendgrid,
    "twilio": verify_twilio,
    "huggingface": verify_huggingface,
    "deepseek": verify_deepseek,
    "aws": verify_aws,
}


def provider_for_pattern(pattern_name: str) -> str | None:
    """Map a leak-detector pattern name to a provider key, or None."""
    low = pattern_name.lower()
    if low.startswith("openai"):
        return "openai"
    if low.startswith("anthropic"):
        return "anthropic"
    if low.startswith("github"):
        return "github"
    if low.startswith("aws"):
        return "aws"
    if low.startswith(("google", "gcp")):
        return "google"
    if low.startswith("slack"):
        return "slack"
    if low.startswith("stripe"):
        return "stripe"
    if low.startswith("sendgrid"):
        return "sendgrid"
    if low.startswith("twilio"):
        return "twilio"
    if low.startswith(("huggingface", "hf-")):
        return "huggingface"
    if low.startswith("deepseek"):
        return "deepseek"
    return None


async def verify_by_pattern(pattern_name: str, token: str) -> VerifyOutcome:
    """Dispatch a token to the correct verifier based on pattern name."""
    provider = provider_for_pattern(pattern_name)
    if provider is None:
        return VerifyOutcome(
            kind="unverifiable",
            reason=f"No verification endpoint is known for pattern {pattern_name!r}",
        )
    verifier = _PROVIDER_DISPATCH.get(provider)
    if verifier is None:
        return VerifyOutcome(
            kind="unverifiable",
            reason=f"No verifier registered for provider {provider!r}",
        )
    try:
        return await verifier(token)
    except httpx.HTTPError as exc:
        return VerifyOutcome(
            kind="unverifiable",
            reason=f"{provider} request failed: {type(exc).__name__}",
        )