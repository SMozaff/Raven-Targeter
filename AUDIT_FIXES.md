# Audit / V0.3 Changes

This build keeps the earlier endpoint-extraction and discovery fixes and adds the requested end-user API configuration model.

## New API configuration model

- GitHub token is configured in `Settings / APIs`.
- Search API provider, engine and key are configured in `Settings / APIs`.
- Secrets are saved through OS `keyring`, not SQLite or QSettings.
- Environment secret variables remain optional overrides only.
- Search cannot start when a selected source lacks the credential it requires.

## Web Search API

V0.3 includes a SerpAPI adapter so the Search API setting is functional rather than decorative.

- provider: SerpAPI
- engines exposed: Google, Baidu, Bing, Yandex
- web-only and GitHub+web combined search supported
- Search API errors do not include request URLs/API keys

## CI/build

The GitHub Actions workflow now:

- lints
- tests
- compiles Python sources
- repeats tests on Linux, Windows and macOS
- builds a native PyInstaller desktop artifact on each OS
- uploads packaged artifacts for download from the workflow run
