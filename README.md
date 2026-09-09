# Raven-Targeter 0.3

Raven-Targeter is a cross-platform desktop application for discovering **recent user-created AI API projects and public API endpoints**.

The application has two independent discovery sources:

1. **GitHub API** — repositories, code, issues and pull requests.
2. **Web Search API** — optional public-web discovery through a user-configured search provider. V0.3 includes a SerpAPI connector with Google, Baidu, Bing and Yandex engine selections.

Default AI targets are OpenAI, Anthropic/Claude, Gemini, xAI/Grok and DeepSeek.

## API setup is controlled by the end user

The desktop GUI now contains **Settings / APIs**.

### GitHub API

The user enters their own GitHub personal access token and can:

- Save Securely
- Test GitHub API
- Clear the stored token

### Web Search API

The user can choose:

- Provider: `disabled` or `serpapi`
- Engine: `google`, `baidu`, `bing`, or `yandex`
- Their own Search API key

The Search API can be tested before use. The SerpAPI test performs one minimal real search and can consume one API request.

### Credential security

Desktop credentials are stored through Python `keyring`, using the operating-system credential store:

- Windows Credential Manager
- macOS Keychain
- the configured Linux keyring/Secret Service

Raven does **not** save API keys in:

- SQLite
- exported discovery files
- GUI settings (`QSettings`)
- source code

`GITHUB_TOKEN` and `SEARCH_API_KEY` environment variables remain available only as explicit advanced/headless/CI overrides. The GUI never writes those environment variables or `.env` files.

The **Start Search** button is enabled only when all selected search sources have the required user-supplied credentials.

## Search behavior

### GitHub

The GitHub discovery layer includes:

- repository search
- code search
- issue search
- pull-request search
- `created:` and `pushed:` recency axes
- bounded README inspection
- bounded code-content inspection
- API endpoint extraction
- repository/code evidence merging
- rate-limit bucket tracking

### Web Search API

When enabled, the web-search layer runs focused queries for API wrappers, proxies, gateways, unofficial APIs and compatible implementations.

For the SerpAPI Google engine Raven applies a server-side `qdr` lookback filter. Other engines are supported as discovery engines but Raven does not invent publication dates where the search provider does not return one.

## Raven-Validator interchange

Exports use the versioned schema:

```text
raven-discovery-export-v1
```

Example:

```json
{
  "schema": "raven-discovery-export-v1",
  "discoveries": [
    {
      "title": "user/project",
      "source_url": "https://github.com/user/project",
      "provider": "openai",
      "classification": "proxy",
      "candidate_endpoints": [
        {
          "url": "https://api.example.com/v1",
          "kind": "api-base",
          "confidence": 0.9,
          "evidence": "README deployment/config evidence"
        }
      ]
    }
  ]
}
```

GitHub repository URLs are not exported as API endpoints.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
python app.py
```

The first launch opens **Settings / APIs** when no GitHub credential is configured.

## Optional environment configuration

Copy `.env.example` only for headless/advanced use:

```text
GITHUB_TOKEN=
SEARCH_API_KEY=
RAVEN_TARGETS=openai,anthropic,gemini,grok,deepseek
RAVEN_LOOKBACK_DAYS=10
RAVEN_MAX_RESULTS_PER_SOURCE=200
RAVEN_SEARCH_API_PROVIDER=disabled
RAVEN_SEARCH_API_ENGINE=google
RAVEN_SEARCH_API_BASE_URL=https://serpapi.com/search.json
RAVEN_SEARCH_API_MAX_QUERIES=10
```

For normal desktop use, leave secrets out of `.env` and use **Settings / APIs**.

## Tests

```bash
pytest
ruff check .
python -m compileall -q src app.py
```

Network behavior is mocked in the unit tests. No live GitHub or Search API credential is required by the normal test suite.

## GitHub Actions: test + build every desktop platform

`.github/workflows/ci.yml` performs:

1. Linux lint, unit tests and Python byte-code compilation.
2. A matrix build on:
   - Ubuntu / Linux
   - Windows
   - macOS
3. `ruff`, `pytest` and `compileall` again on each target operating system.
4. PyInstaller builds for each platform.
5. Artifact packaging and upload through `actions/upload-artifact`.

Generated artifacts are:

```text
Raven-Targeter-Linux-<arch>
Raven-Targeter-Windows-<arch>
Raven-Targeter-macOS-<arch>
```

The workflow is triggered by pushes, pull requests, version tags (`v*`) and manual `workflow_dispatch` runs.

## Build locally

```bash
pip install -e ".[dev,packaging]"
```

Linux / Windows one-file build:

```bash
python -m PyInstaller --noconfirm --clean --windowed --onefile \
  --name Raven-Targeter --paths src \
  --collect-all keyring --collect-all pydantic --collect-all pydantic_settings \
  --hidden-import raven_targeter --hidden-import raven_targeter.gui.main_window \
  app.py
```

On macOS, remove `--onefile` to produce `dist/Raven-Targeter.app`.

## Current security model

- API credentials originate with the end user.
- Secrets are stored in the OS keychain.
- Search execution receives credentials only at runtime.
- Secrets are not placed in discovery models or export schemas.
- Search API transport errors are normalized without embedding request URLs, preventing query-string API keys from leaking into UI errors.
- Public endpoint extraction rejects obvious GitHub pages and private/loopback IP endpoints before handoff to Raven-Validator.
