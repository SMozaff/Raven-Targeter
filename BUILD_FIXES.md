# GitHub Actions Build Fixes

The first GitHub Actions run (`34302009217`) failed in the **Ruff** step before tests or desktop builds could start.

## Root causes found in the run log

- Ruff style errors in `github.py`, `sanitizer.py`, `main_window.py`, `dates.py`, and two current tests.
- The GitHub repository also contained legacy tests from the older pre-v0.3 implementation. The v0.3 source tree had been copied over an existing repository without deleting obsolete files, so after lint was fixed those old tests would fail during collection against APIs/functions that no longer exist.
- `actions/checkout@v4` and `actions/setup-python@v5` produced Node 20 deprecation warnings on the 2026 hosted runners. They were not the direct failure, but this workflow now uses the current v7 actions.

## Fixes in this package

- Fixed all Ruff findings reported by run `34302009217` in the current v0.3 source/test set.
- Kept only the tests that belong to the v0.3 implementation, avoiding stale test/source mismatches.
- Updated Actions to `actions/checkout@v7` and `actions/setup-python@v7`.
- Runs lint, pytest and `compileall` before builds.
- Re-runs lint/tests/compile on Linux, Windows and macOS before packaging each native build.
- Verifies that the expected native build exists before packaging/uploading it.

## Important deployment instruction

Replace the repository contents with this tree; do **not** copy it over the existing repository without deleting removed files first. Otherwise the obsolete legacy tests will remain and CI will still fail.
