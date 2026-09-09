# Development Tracker

## Current
Raven-Targeter 0.3 — user-managed API settings + optional web-search API + cross-platform CI/build.

## Completed
- GitHub token entry in desktop Settings / APIs
- secure GitHub token storage through OS keychain
- GitHub API connection test
- Search API provider/engine/key settings
- secure Search API key storage through OS keychain
- SerpAPI connector (Google/Baidu/Bing/Yandex engine selection)
- Search API connection test
- Start Search gating based on selected source credential readiness
- GitHub-only, web-only and combined search modes
- created+pushed GitHub discovery axes
- provider round-robin GitHub query ordering
- bounded README/code enrichment
- endpoint extraction
- repo/code identity merge
- versioned Validator interchange
- GitHub rate-resource tracking
- GitHub Actions lint/test/compile matrix
- PyInstaller Linux/Windows/macOS build artifacts
- credential-store, SerpAPI and web-pipeline tests

## Verification
- `python -m compileall -q src app.py` — PASS
- `pytest -q` — 9 passed in the build environment
- GUI smoke could not be executed in the build container because PySide6 is not installed there; GitHub Actions installs project dependencies before testing/building.
- Ruff is executed by GitHub Actions; Ruff is not installed in the current offline build container.

## Next
- Run workflow on GitHub and confirm three uploaded desktop artifacts.
- Live-test GitHub API using an end-user token entered through the desktop Settings page.
- Live-test Search API using an end-user SerpAPI key.
- Add additional web-search provider adapters behind the same Settings interface if needed.

## v0.4.0 — Responsible-Disclosure Leak Detection (added, this pass)

**Goal:** find likely-exposed API credentials in public GitHub code so a
human can responsibly notify the repo owner — without the tool ever
capturing, storing, or displaying the actual secret.

### Added
- `core/leak_detector.py` — pattern matching (OpenAI/Anthropic/GitHub/AWS
  key shapes + generic bearer/assignment patterns) + Shannon-entropy
  confidence scoring + placeholder/example-context suppression. The raw
  matched string exists only in local scope inside `detect_leaks()`; every
  return field is a redacted preview, never the working credential.
- `models.LeakAlert` — repo identity/URL, file, line, pattern, confidence,
  entropy, redacted preview, disclosure `status` (new/reviewed/disclosed/
  dismissed). No field can hold a raw secret.
- `AdapterSearchResult.leak_alerts` — adapters can now return alerts
  alongside discoveries/errors.
- `adapters/github.py` — leak detection now runs on raw code/README content
  *before* `redact_text()` scrubs it (redaction destroys the entropy signal
  needed for scoring); only the resulting `LeakAlert` objects are kept.
- `database/database.py` — new `leak_alerts` table + save/list/update-status.
- `gui/main_window.py` — new **Disclosure** tab: table of alerts (confidence,
  pattern, redacted preview, repo, file, line, status) + buttons to mark
  Reviewed / Disclosed / Dismissed. Never renders a raw secret.
- `services/search_service.py` — `SearchPipeline.run()` now returns
  `(discoveries, errors, leak_alerts)` — a breaking signature change,
  updated at both call sites (GUI worker, existing web-pipeline test).
- Tests: `test_leak_detector.py` (14), `test_github_leak_alerts.py` (3),
  `test_leak_alert_persistence.py` (5) — 22 new tests, all asserting the
  raw secret never appears in any output field, in addition to correctness.

### Bugs found and fixed during this pass
- **leak_detector**: when two secrets appeared on the same line, the first
  finding's redacted context line only redacted its own secret, leaving the
  second one in cleartext in `context_line_redacted`. Caught by
  `test_multiple_findings_on_same_line_both_captured`. Fixed by redacting
  every secret found on a line before building any finding's context field.
- **models.py**: `Discovery.utc_dates` and (newly written) `LeakAlert.utc_date`
  validators assumed an already-parsed `datetime`, but Pydantic passes the
  raw value in `mode="before"` — so reloading a `Discovery` with a real date
  from the database (`Database.list()`, which round-trips through
  `model_dump_json()`/`json.loads()`) raised `AttributeError: 'str' object
  has no attribute 'tzinfo'`. This was a **pre-existing bug in `Discovery`**,
  not something introduced by this pass — it just had no prior test that
  populated a date field and reloaded from SQLite. Fixed both validators to
  parse ISO strings before validating.

### Explicitly out of scope for this pass (unchanged)
This work only makes leak *findings* reportable — it does not add any
mechanism to test whether a found credential is live/working, and does not
change the GitHub-only vs. web-search scope debate from earlier in the
project history. `AGENTS.md`'s "never test credentials" boundary continues
to apply to `LeakAlert` findings.

### Verification
```
$ ruff check .
All checks passed!

$ pytest -q
31 passed
```
Also manually verified headlessly (`QT_QPA_PLATFORM=offscreen`):
- `MainWindow` constructs with a "Disclosure" tab present
- `_done()` populates `disclosure_table` and the status bar correctly from
  real `LeakAlert` data
- Mark Reviewed/Disclosed/Dismissed updates `_leak_alerts[i].status`
- Full `run_app(get_settings())` startup path returns cleanly

