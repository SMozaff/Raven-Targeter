# AGENTS.md — Durable Instructions for Raven-Targeter

This file orients any AI coding agent (or human) picking up this project in a
future session. Read this before making changes.

## What this project is

A cross-platform PySide6 desktop app that discovers **recently created or
recently active, user-created AI API projects on GitHub** — unofficial
wrappers, SDKs, proxies, gateways, OpenAI-compatible adapters, and related
issues/PRs — for a configurable set of AI provider targets (default: OpenAI,
Anthropic, Gemini, Grok, DeepSeek).

## Product principle (do not violate)

The app must answer: *"What new user-created AI APIs, wrappers, gateways,
integrations, or implementation discussions appeared recently on GitHub?"*

It must **not** answer by asking an LLM what it remembers. Every discovery
must originate from a real GitHub API response and retain its source URL,
raw evidence, and timestamps.

## V1 scope (current)

- GitHub only: repository search, code search, issue search, PR search,
  README enrichment on shortlisted repos.
- `GitHubGistAdapter` exists as a documented, disabled-by-default placeholder.
  Do not implement real Gist search in V1 — GitHub has no full-text Gist
  search API; real Gist discovery is deferred to the future web-search layer.
- SQLite persistence via SQLAlchemy 2.x.
- Deterministic (non-LLM) classification and scoring.
- JSON/CSV export.
- PySide6 desktop GUI (Dashboard, Search, Results, Settings).

## Explicitly out of scope for V1 — do not add without being asked

- Any general web search adapter (Brave/Google/Bing/SerpAPI/etc.)
- Reddit, Hacker News, NPM, PyPI adapters
- Public shared-chat-page discovery (chatgpt.com/share, claude.ai/share, etc.)
  — this touches other users' shared content and needs explicit human
  sign-off on scope/ToS considerations before any implementation is attempted.
- LLM-based summarization or classification
- Playwright/Selenium or any headless browser
- Cloning or executing code from discovered repositories, ever

## Non-negotiable engineering rules

- UTC-aware datetimes everywhere. Naive datetimes are a bug — see
  `utils/dates.py::ensure_utc`.
- Distinguish `created_at`, `updated_at`, and `pushed_at` on repositories.
  Never conflate them.
- Never build GitHub API query URLs by string concatenation — always use
  httpx `params={...}`.
- Never silently treat an HTTP error as "zero results." Surface it.
- Redact anything resembling a credential (`sk-...`, bearer tokens, etc.)
  found in fetched public text before storing or displaying it — see
  `core/sanitizer.py`.
- Never store the user's own GITHUB_TOKEN value in the database or logs.
- Never store discovered/harvested API keys, even redacted-looking ones.
- No `except Exception` without re-raising or converting with context.
- Business logic (`core/`, `adapters/`, `database/`, `services/`) must stay
  independent of the GUI layer — GUI imports services, not the other way.
- Keep scoring weights centralized and documented (currently in
  `core/scorer.py`); write tests when weights change.

## Before declaring any milestone complete

```bash
ruff check .
pytest
```

Both must be clean. Update `DEVELOPMENT_TRACKER.md` as you go, not at the end.

## Repository structure

See `DEVELOPMENT_TRACKER.md` for current milestone status and
`README.md` for setup/run instructions.
