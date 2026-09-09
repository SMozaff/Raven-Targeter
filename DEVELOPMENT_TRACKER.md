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
