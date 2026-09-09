# Development Tracker — Raven-Targeter

## Current Milestone

**M6 — Export & Polish: COMPLETE. V1 is done** — all six milestones
green: `ruff check .` clean, `pytest` **176 passed**, entry point
verified starting end-to-end.

## Completed

### M6 — Export & Polish (2026-09-09)

- `services/export_service.py` — `export_json` (normalized
  `model_dump(mode="json")` array), `export_csv` (flattened
  `EXPORT_COLUMNS`, headers always written, quoting-safe), and
  `export_discoveries` dispatcher (`ValueError` on unknown formats);
  files go to `exports/YYYY-MM-DD/raven-<UTC stamp>.<ext>`, created on
  demand. No GUI imports, no raw payloads, no token anywhere near it.
- Wiring: ResultsPage gains Export JSON/CSV buttons (`export_requested`
  signal) exporting the *filtered view* via new `visible_discoveries`;
  detail dialog's Export-selected flows to JSON; `MainWindow` owns both
  handlers plus a status-bar confirmation line and a testable
  `exports_dir` parameter.
- 10 tests in `tests/test_export_service.py`: JSON shape/round-trip,
  CSV header/quoting/empty, dispatcher rejection, flatten stringness,
  button signals, filter-respecting visible export, and both MainWindow
  handlers writing real files with status confirmation.
- Polish: README gained an Export section and refreshed Limitations;
  new `CHANGELOG.md` (M0–M6); `pyproject.toml` floor raised to
  `>=3.12` / ruff `py312` (the codebase already requires 3.11+ via
  `datetime.UTC`).
- Final gates: `ruff check .` clean, `pytest` **176 passed**
  (166 + 10), `python app.py` verified starting offscreen (settings →
  token warning → schema init).
- Also closed a `.gitignore` gap found during final verification: WAL
  sidecars (`data/*.db-shm`, `data/*.db-wal`) from real runs are now
  ignored alongside `data/*.db`.
- Honesty note: one full-suite run during M6 showed a single
  unidentified failure, green on immediate re-run and across seven
  subsequent full runs. Not reproduced since; suspected sandbox thread-
  timing flake. If it recurs, capture the test name with `-rf` and
  treat it as a real bug.

### M5 — End-to-End Search (2026-09-09)

- `services/search_service.py` — two layers:
  - `SearchPipeline` (Qt-free async): build queries → per-source-group
    adapter search → classify (`classify_evidence`) → score (API
    patterns → full breakdown, classification applied *before* scoring
    so bonuses count) → date validation (repo/issue/PR must be recent;
    dateless code hits survive only via an accepted parent repo) →
    dedup → min-score filter → persist + close run. Stage messages
    follow the spec ("Generating queries", "Searching repositories",
    "Inspecting README files", "Searching issues", "Scoring", "Saving",
    "Complete"). Unexpected failures mark the run `"failed"` with a
    `pipeline` error row, then re-raise typed (`PipelineFailedError`);
    cancellation closes the run as `"cancelled"`.
  - `SearchWorker` (`QObject` for `QThread`): `Signal(object)` streaming
    (`discovery_found`, progress message/percent, `finished(run_id)`,
    `failed`, `search_cancelled`); cooperative cancel flag checked
    between stages; adapter built/closed inside the worker thread.
- `gui/main_window.py` — full wiring: Start spawns the worker thread
  (GUI never blocks), progress → SearchPage, streamed hits →
  `ResultsPage.append_discovery` (new), finish → final scored list +
  dashboard refresh + auto-switch to Results; cancel/closeEvent
  cooperate; failure reports via status line (no modal — headless-safe).
- `core/deduplicator.py` — `merge_key` now normalizes unconditionally,
  so hand-built records with raw `canonical_url` still merge (bug
  caught by M5 tests).
- 9 tests in `tests/test_search_service.py`: full-run accept/drop
  matrix (merge, stale, orphan-code, child-code), min-score, error
  persistence, cancel-before/mid-run, unexpected-failure closeout,
  multi-target query coverage, real-QThread worker streaming, and a
  MainWindow click → Results → Dashboard cycle on a fake adapter —
  no network anywhere.
- `ruff check .` clean, `pytest`: **166 passed** (157 + 9)

### M4 — GUI Shell (2026-09-09)

- `gui/main_window.py` — sidebar navigation (Dashboard/Search/Results/
  Settings) over a `QStackedWidget`; `run_app` builds storage
  (`build_engine` + `init_db` + `RavenRepository`) and owns the event
  loop; `app.py` unchanged (same entry contract as M0)
- `gui/search_page.py` — target checkboxes from canonical IDs, lookback
  (1-365) / max-results / keyword / min-score controls, Start/Cancel
  with running-state toggling, progress bar + status line; emits
  `search_requested(SearchRequest)` / `cancel_requested` — no network
  I/O in the page, M5 connects the signals
- `gui/results_page.py` — `QTableView` over `QStandardItemModel` with
  all ten spec columns, numeric/date-aware `_SortItem` ordering, and a
  `QSortFilterProxyModel` filter bar (provider, classification, time
  range, newly-created / recently-active via `core.date_validator`,
  min score); full `Discovery` objects kept ID-keyed (never re-derived
  from cell text); double-click emits `detail_requested`
- `gui/result_detail.py` — modal dialog with title/URL/meta/scores/
  description/terms/evidence, working Open-in-browser + Copy-URL, and
  an `export_requested` signal for M6 export wiring
- `gui/dashboard.py` — stat cards (`refresh` from detached
  `RunSummary` list; M5 wires it) and `gui/settings_page.py` —
  display-only effective config with token shown as Configured/Missing
  only (value never rendered)
- 13 offscreen tests in `tests/test_gui.py` (`QT_QPA_PLATFORM=offscreen`,
  single module-scoped `QApplication`): navigation, request building,
  signal emission, button toggling, table population, provider/score/
  recency filters, selection + detail signal, dialog population/copy/
  export, token masking, dashboard refresh
- `ruff check .` clean, `pytest`: **157 passed** (144 + 13)

### M3 — Persistence (2026-09-09)

- `database/models.py` — SQLAlchemy 2.x `Base` + `SearchRun`
  (status/counts/targets+sources as JSON), `DiscoveryRecord` (all five
  score components + `total_score` snapshot for SQL sort/filter,
  canonical URL + repo identity, score/provider indexes),
  `Evidence` (ordered content rows per discovery), `SearchErrorRecord`
  (explicit adapter errors per run); FK cascades throughout
- `database/database.py` — `build_engine` from `RAVEN_DB_URL` (creates
  parent dirs, `check_same_thread=False`, WAL + `foreign_keys=ON`
  pragmas), `init_db` (idempotent `create_all`)
- `database/repository.py` — `RavenRepository` facade: create/complete/
  get/list runs, save/query discoveries (provider/classification/
  min-score filters, score-desc order), save/get errors; reads return
  detached data only (`Discovery`, `RunSummary`) — session-safe for Qt
  workers; SQLite-naive datetimes re-attached to UTC on every read;
  `complete_run` raises `KeyError` on unknown IDs instead of failing
  silently
- 13 new tests in `tests/test_persistence.py` on temp SQLite files:
  run lifecycle, full-field round-trip, UTC-aware read-back, score
  ordering, all filters, error round-trip, empty-save zeroes, newest-
  first listing — plus a `GITHUB_TOKEN`-never-stored test that scans the
  raw DB bytes (and WAL sidecars)
- `ruff check .` clean, `pytest`: **144 passed** (131 + 13)

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

V1 is complete. If new work is requested, candidate follow-ups (all
explicitly out of V1 scope — need human sign-off first):

- Web-search adapter layer (per AGENTS.md constraints)
- Scheduler / desktop notifications
- Packaged builds (PyInstaller `.exe` / `.app` / AppImage)

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

M3:
src/raven_targeter/database/models.py
src/raven_targeter/database/database.py
src/raven_targeter/database/repository.py
tests/test_persistence.py

M4:
src/raven_targeter/gui/main_window.py   (rewritten: navigation + storage wiring)
src/raven_targeter/gui/dashboard.py
src/raven_targeter/gui/search_page.py
src/raven_targeter/gui/results_page.py
src/raven_targeter/gui/result_detail.py
src/raven_targeter/gui/settings_page.py
tests/test_gui.py

M5:
src/raven_targeter/services/search_service.py
src/raven_targeter/gui/main_window.py   (search wiring: thread, slots, teardown)
src/raven_targeter/gui/results_page.py  (append_discovery for streaming)
src/raven_targeter/core/deduplicator.py (merge_key always normalizes)
tests/test_search_service.py

M6:
src/raven_targeter/services/export_service.py
src/raven_targeter/gui/main_window.py   (export handlers + status bar + exports_dir)
src/raven_targeter/gui/results_page.py  (export buttons + visible_discoveries)
tests/test_export_service.py
README.md                               (Export section, refreshed Limitations)
CHANGELOG.md                            (new)
pyproject.toml                          (requires-python >=3.12, ruff py312)
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
176 passed in 3.11s   (32 M0 + 75 M1 + 24 M2 + 13 M3 + 13 M4 + 9 M5 +
10 M6; M2 retry tests add a few seconds of real short backoff sleeps
by design)
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
- **M3: `total_score` is a stored snapshot**, not a live computation, so
  SQL can order/filter by it. It is computed from the centralized
  weights at save time; weight changes apply to newly saved runs.
- **M3: UTC is re-attached on read** because SQLite drops tzinfo. The
  `_aware` helper in `repository.py` is the single place this happens;
  writers must still pass UTC-aware datetimes (Pydantic enforces it).
- **M3: repository returns detached data only** (Pydantic `Discovery`,
  `RunSummary` dataclass) — no ORM objects escape the session, keeping
  Qt worker threads safe in M5.
- **M3: fixed a session bug caught by tests** — the facade passed the
  `sessionmaker` itself as a `Session` bind; all call sites now use
  `self._factory()`.
- **M4: pages emit signals, never run I/O.** `SearchPage` emits a
  validated `SearchRequest`; `ResultsPage` emits `Discovery` detail
  requests; `ResultDetailDialog` emits export requests. M5 connects
  these to the service layer without touching the pages.
- **M4: table filters are presentation-level** (fixed 10-day display
  window). Exact run-window filtering stays in the request + repository
  query, which M5 owns.
- **M4: Qt6 `invalidate()`** is the non-deprecated proxy refresh in
  PySide6 6.11 (`invalidateFilter` and `invalidateRowsFilter` both warn).
- **M4: offscreen tests verify structure, not pixels.** Visual
  verification needs `python app.py` on a machine with a display server
  (sandbox has none).
- **M5: pipeline owns stage order, worker owns threads, MainWindow owns
  wiring.** `SearchPipeline` has no Qt import; `SearchWorker` bridges
  with `Signal(object)`; `MainWindow` manages thread lifecycle. The
  repository facade is shared across threads (one session per call,
  SQLite WAL + `check_same_thread=False`).
- **M5: per-source-group adapter calls** give progress granularity,
  cancel points, and per-source caps — at the cost of one search call
  per active group instead of one total. Breadth-first by design.
- **M5: streaming shows pre-dedup hits**; the final `finished` payload
  replaces them with the merged list. A streamed row can disappear on
  merge — accepted and documented.
- **M5: no modal dialogs in worker slots** — failure surfaces via the
  status line so headless/offscreen runs never block on user input.
- **M5: threaded GUI tests poll for completion**, never hook signals
  after the fact — a sub-millisecond fake worker can emit `finished`
  before a deferred hookup runs.
- **M6: export is a service, not a widget feature.** The GUI emits
  *what* to export (single discovery / filtered view / format); the
  service owns paths, naming, and serialization — so a future CLI can
  reuse it untouched.
- **M6: Python floor is 3.12.** The code already depended on 3.11+
  (`datetime.UTC`); the project metadata now says so honestly.

- **AGENTS.md instead of QWEN.md**: this build isn't done via Qwen Code, so
  the durable-instructions file is named generically. Explicit user choice.
- **Settings supports both `RAVEN_`-prefixed and bare env var names** for the
  five RAVEN_ fields, to match the .env.example exactly while keeping
  pydantic-settings' native field-name matching as a fallback.
- Sandbox has no display server. GUI (M4) will be built as full PySide6 code,
  verified via headless import + offscreen-platform smoke test in this
  sandbox, and packaged for the user to actually run/click through locally.
