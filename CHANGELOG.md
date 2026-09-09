# Changelog — Raven-Targeter

All notable changes to this project are recorded here. V1 follows the
six-milestone plan in `DEVELOPMENT_TRACKER.md`.

## [0.1.0] — 2026-09-09 — V1 complete

### Added (by milestone)

- **M0 — Repository Bootstrap:** project skeleton, `pyproject.toml`,
  Pydantic `Settings` (env/`.env` loading, token-presence check),
  UTC structured logging, UTC date helpers, URL canonicalization,
  `app.py` entry point, full README, `.env.example`.
- **M1 — Core Domain:** target/alias registry, normalized `Discovery` /
  `SearchRequest` / `QueryVariant` models, focused query builder
  (structured date qualifiers; none for code search), UTC date
  validator distinguishing created/pushed/updated, canonical-URL
  deduplicator, centralized 35/30/15/10/10 scorer with deterministic
  classifier, credential sanitizer.
- **M2 — GitHub Adapter:** authenticated async client; repository, code,
  issue, and PR search via `params={...}`; README enrichment (redacted,
  truncated, non-fatal); tenacity retries honoring `Retry-After` /
  rate-limit headers; explicit error model; disabled-by-default Gist
  placeholder (no faked Gist search).
- **M3 — Persistence:** SQLAlchemy 2.x models (`search_runs`,
  `discoveries`, `evidence`, `search_errors`), WAL SQLite engine
  factory, repository facade returning detached data, UTC re-attached
  on read, score snapshot columns for SQL sort/filter.
- **M4 — GUI Shell:** PySide6 navigation (Dashboard/Search/Results/
  Settings), search controls emitting validated requests, sortable
  ten-column results table with proxy-model filters, detail dialog
  (open/copy), token-status-only settings page.
- **M5 — End-to-End Search:** Qt-free async pipeline (classify → score
  → date-filter → dedup → min-score → persist) plus `QThread` worker
  with progress/streaming/cancel signals; MainWindow wiring with live
  results, dashboard refresh, and auto-switch to Results.
- **M6 — Export & Polish:** JSON/CSV export of normalized discoveries
  to `exports/YYYY-MM-DD/` from the results view and detail dialog;
  this changelog; README export docs.

### Verification

- `ruff check .` clean and full `pytest` suite green at every milestone
  (176 tests total), including mocked-HTTP adapter tests, temp-file
  persistence tests, and offscreen GUI/threading tests. No live GitHub
  calls in the suite.
