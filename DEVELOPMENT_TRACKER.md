# Development Tracker — Raven-Targeter

## Current Milestone

**M2 — GitHub Adapter: COMPLETE.** Next: M3 — Persistence.

## Completed

### M2 — GitHub Adapter (2026-09-09)

- `adapters/base.py` — `SearchAdapter` contract, explicit `SearchError`
  (source/status/message/retryable/timestamp), `AdapterSearchResult`
  (hits + errors; HTTP failures are never silent zeroes)
- `adapters/github.py` — authenticated httpx `AsyncClient`
  (`Accept: application/vnd.github+json`, `User-Agent`, bearer token only
  when configured; token never logged):
  - repo/code/issue/PR search via `/search/repositories`, `/search/code`,
    `/search/issues` (+ injected `type:issue` / `type:pr`); every call uses
    `params={...}`, never URL string concatenation
  - code search carries no date qualifiers (API limitation); code hits keep
    parent `repo_identity` and dateless timestamps for engine-side joining
  - issues/PRs parse `repository_url` into parent identity; `pushed_at`
    stays `None` (never conflated)
  - normalization redacts descriptions/bodies, records alias matched
    terms, sets canonical URL + repo identity
  - README enrichment (raw `Accept`, first 10 repos by default): redacted,
    truncated to 2000 chars, appended as evidence; failures are non-fatal
    explicit errors
  - retries (tenacity, 1 + 3 bounded exp-backoff + jitter): 429,
    500/502/503/504, rate-limit 403s, timeouts, connection errors;
    `Retry-After` / `x-ratelimit-reset` honored (capped at 120 s, beyond
    which it fails explicitly instead of hanging); known quota exhaustion
    respected between calls
  - never retried: 401, 422 (message includes API detail), non-rate 403,
    malformed JSON
  - per-query `max_results` cap, single page per query (breadth over
    depth), injectable transport/sleep/wait for tests
- `adapters/github_gists.py` — `GitHubGistAdapter`, `enabled = False`;
  `search()` returns zero discoveries + an explicit disabled-state error
  (no full-text Gist search API exists; real coverage deferred to the
  future web-search layer; nothing is faked)
- 24 new tests in `tests/test_github_adapter.py`, all on
  `httpx.MockTransport` (no live GitHub): normalization, params encoding,
  auth header present/absent, 401, forbidden-403, rate-limit-403 (wait
  honored), 422 detail, 429/503 retry-then-success, persistent-500
  exhaustion (bounded attempts), timeout retryable error, malformed JSON,
  partial failure, type qualifiers, codeless dates, Unicode `q`,
  README redact/truncate, README-404 survival, gist placeholder,
  `from_settings`, result cap
- `ruff check .` clean, `pytest`: **131 passed** (107 + 24)

### M1 — Core Domain (2026-09-09)

- `config/targets.py` — canonical target IDs, display names, normalize/lookup
  helpers
- `config/aliases.py` — data-driven `TargetAliases` registry (names x
  intents) for all five default targets; `find_targets_in_text` matcher
- `models.py` — normalized Pydantic models: `Discovery` (all five score
  components stored explicitly + `total_score`), `SearchRequest`
  (spec defaults: 10-day lookback, 200 max/source, 0.0 min score),
  `QueryVariant` (keyword text + structured qualifiers, `dedup_key`);
  naive/non-UTC datetimes rejected at validation
- `core/query_builder.py` — focused `name x intent` variants per target and
  search type (12 repo + 4 issue + 2 PR + 4 code = 22/target max, ~110 total
  before dedup); `created:>=YYYY-MM-DD` qualifiers on repo/issue/PR, **no**
  date qualifiers on code search (GitHub API limitation); user keywords
  appended; variants deduplicated, deterministic order
- `core/date_validator.py` — `classify_repo_dates` keeps `created_at` /
  `pushed_at` / `updated_at` independent (`newly_created` vs
  `recently_active`, `date_source` + `date_confidence`); `filter_recent`
  drops unknown-date candidates, never treats them as recent
- `core/deduplicator.py` — merge by canonical URL (case/trailing-slash
  insensitive); unions `matched_terms`/`evidence`, takes per-component score
  maxima, appends merge-provenance note; distinct issue/PR URLs stay
  separate; `attach_repo_identity` links issues/PRs to parent repos
- `core/scorer.py` — centralized `SCORING_WEIGHTS` (35/30/15/10/10) with
  `combine_scores`; deterministic `classify_evidence` (openai-compatible >
  proxy > gateway > sdk > wrapper > client > example > automation >
  discussion-for-issues > unknown fallback); log-scaled engagement;
  `score_discovery` returns full `ScoreBreakdown`; verified
  implementation-code outranks name-mention end to end
- `core/sanitizer.py` — one-way redaction of `sk-`/`sk-ant-`/GitHub/Slack/
  AWS/Bearer/generic api_key secrets; `detect_api_patterns` and
  `find_matched_terms` feed scoring (detection, not harvesting)
- Package `__init__.py` added for `core`, `adapters`, `database`, `services`
- 75 new tests: `test_targets_aliases`, `test_models`,
  `test_query_builder`, `test_date_validator`, `test_deduplicator`,
  `test_scorer`, `test_sanitizer` — all offline, no network
- `ruff check .` clean (one import-order auto-fix), `pytest`: **107 passed**

### M0 — Repository Bootstrap (earlier)

- Directory skeleton (`src/raven_targeter/{config,core,adapters,database,services,gui,utils}`, `tests`, `data`, `exports`)
- `pyproject.toml` with dependencies and dev deps
- `.gitignore`, `.env.example`
- `config/settings.py` — Pydantic `Settings` with env loading, RAVEN_-prefixed var support, `has_github_token` property
- `utils/logging.py` — UTC-timestamped structured logging
- `utils/dates.py` — UTC cutoff calculation, GitHub timestamp parsing, lookback filtering
- `utils/urls.py` — URL canonicalization for dedup, canonical repo identity
- `app.py` — entry point (loads settings, configures logging, warns on missing token)
- `gui/main_window.py` — minimal M0 stub (`run_app`) so `app.py` starts end-to-end; real navigation is M4
- `AGENTS.md` — durable instructions for future sessions (named AGENTS.md per
  explicit user decision, spec originally said QWEN.md — this repo is not
  built with Qwen)
- `README.md` — full setup/env/run/test/limitations docs
- 32 tests across `test_settings.py`, `test_dates.py`, `test_urls.py`
- Bug caught + fixed during verification: `canonicalize_url` wasn't
  lowercasing the path, so `github.com/Foo/Bar` and `github.com/foo/bar`
  canonicalized differently. Fixed; GitHub-specific behavior documented
  inline since it wouldn't generalize to case-sensitive hosts.

## In Progress

Nothing — M1 closed out.

## Next

- M3 — Persistence: SQLAlchemy 2.x models (`search_runs`, `discoveries`,
  `evidence`, `search_errors`), engine/session factory from `RAVEN_DB_URL`,
  repository pattern (save/query runs + discoveries), tests on a temp
  SQLite file. Never store `GITHUB_TOKEN` or harvested secrets.

## Files Changed This Milestone

```
M1:
src/raven_targeter/config/targets.py
src/raven_targeter/config/aliases.py
src/raven_targeter/models.py
src/raven_targeter/core/__init__.py
src/raven_targeter/core/query_builder.py
src/raven_targeter/core/date_validator.py
src/raven_targeter/core/deduplicator.py
src/raven_targeter/core/scorer.py
src/raven_targeter/core/sanitizer.py
src/raven_targeter/adapters/__init__.py
src/raven_targeter/database/__init__.py
src/raven_targeter/services/__init__.py
tests/test_targets_aliases.py
tests/test_models.py
tests/test_query_builder.py
tests/test_date_validator.py
tests/test_deduplicator.py
tests/test_scorer.py
tests/test_sanitizer.py

M2:
src/raven_targeter/adapters/base.py
src/raven_targeter/adapters/github.py
src/raven_targeter/adapters/github_gists.py
tests/test_github_adapter.py
DEVELOPMENT_TRACKER.md

M0 (earlier):
pyproject.toml
.gitignore
.env.example
AGENTS.md
DEVELOPMENT_TRACKER.md
README.md
app.py
src/raven_targeter/__init__.py
src/raven_targeter/config/__init__.py
src/raven_targeter/config/settings.py
src/raven_targeter/utils/__init__.py
src/raven_targeter/utils/logging.py
src/raven_targeter/utils/dates.py
src/raven_targeter/utils/urls.py
src/raven_targeter/gui/__init__.py
src/raven_targeter/gui/main_window.py
tests/test_settings.py
tests/test_dates.py
tests/test_urls.py
data/.gitkeep
exports/.gitkeep
```

## Tests Run

```
$ ruff check .
All checks passed!

$ QT_QPA_PLATFORM=offscreen python -m pytest -q
131 passed in 4.02s   (32 M0 + 75 M1 + 24 M2; M2 retry tests add ~4 s of
real short backoff sleeps by design)
```

Also manually verified (per spec's M0 verification step):
- `python -c "from raven_targeter.config.settings import Settings; print(Settings())"` — works
- Full `app.main()` startup path headlessly with `QT_QPA_PLATFORM=offscreen`
  and `QApplication.exec` patched to return immediately — settings load,
  logging configures, missing-token warning fires correctly, window
  constructs, clean exit code 0.

Sandbox has no display server, so the GUI has only been smoke-tested
offscreen, not visually. User will need to run `python app.py` locally to
actually see/click through it.

## Known Issues

- None open. (One found-and-fixed during M0: see above.)

## Architecture Decisions

- **Classification lives in `core/scorer.py`** (`classify_evidence`): the
  build brief lists no separate classifier module for V1, and
  classification feeds relevance/implementation scoring directly. A
  dedicated `analysis/` classifier can be split out later if LLM
  classification ever lands (post-V1).
- **Discovery stores all five score components** (`relevance`,
  `freshness`, `implementation`, `engagement`, `confidence`) so the M4
  result-detail view can expose them and `total_score` stays a pure
  function of stored data.
- **Query qualifiers are structured data**, not pre-rendered `q` strings:
  the M2 adapter merges them into httpx `params={"q": ...}`, keeping the
  "no URL string concatenation" rule satisfiable and qualifier logic
  unit-testable without HTTP.
- **`.venv/` created locally** (gitignored) since the sandbox had no
  project env; `pip install -e ".[dev]"` used for ruff/pytest runs.
- **M2: single page per query (breadth over depth).** The adapter fetches
  page 1 of each focused query and caps total hits; the engine (M5)
  owns cross-query budgeting. Keeps real runs inside rate limits.
- **M2: README enrichment is single-attempt, non-fatal.** Retrying README
  fetches would burn quota for context, not discoveries; failures append
  an explicit `github:readme` error and the discovery survives.
- **M2: `type:issue`/`type:pr` injected by the adapter, not the builder.**
  They are GitHub-search syntax, so they belong to the adapter layer;
  the builder stays provider-agnostic.
- **M2: fixed a layering bug caught by tests** — the adapter read
  `query.keywords`, a `SearchRequest`-only field; user keywords already
  live in `QueryVariant.query_text` via the builder. Adapter now matches
  against alias names/intents + the query text itself.

- **AGENTS.md instead of QWEN.md**: this build isn't done via Qwen Code, so
  the durable-instructions file is named generically. Explicit user choice.
- **Settings supports both `RAVEN_`-prefixed and bare env var names** for the
  five RAVEN_ fields, to match the .env.example exactly while keeping
  pydantic-settings' native field-name matching as a fallback.
- Sandbox has no display server. GUI (M4) will be built as full PySide6 code,
  verified via headless import + offscreen-platform smoke test in this
  sandbox, and packaged for the user to actually run/click through locally.
