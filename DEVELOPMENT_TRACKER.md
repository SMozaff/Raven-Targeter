# Development Tracker — Raven-Targeter

## Current Milestone

**M0 — Repository Bootstrap: COMPLETE**

## Completed

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

Nothing — M0 closed out.

## Next

- M1 — Core Domain: normalized `Discovery`/`SearchRequest` models,
  targets/aliases registry, query builder, date validator, deduplicator,
  scorer, sanitizer + tests (no network yet, all offline-testable)

## Files Changed This Milestone

```
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
32 passed in 0.13s
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

- **AGENTS.md instead of QWEN.md**: this build isn't done via Qwen Code, so
  the durable-instructions file is named generically. Explicit user choice.
- **Settings supports both `RAVEN_`-prefixed and bare env var names** for the
  five RAVEN_ fields, to match the .env.example exactly while keeping
  pydantic-settings' native field-name matching as a fallback.
- Sandbox has no display server. GUI (M4) will be built as full PySide6 code,
  verified via headless import + offscreen-platform smoke test in this
  sandbox, and packaged for the user to actually run/click through locally.
