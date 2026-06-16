# TikTok Metadata Kit

A Python library for TikTok metadata collection, with support for web scraping and the TikTok Research API.

## Quickstart

> TODO


## Development

### Prerequisites

| Tool          | Version         | Notes                                               |
|---------------|-----------------|-----------------------------------------------------|
| Python        | 3.12            | Required; use pyenv or a system package             |
| Git           | any             | Pre-commit hooks are used                           |

### Initial Setup

#### 1. Clone the repository

```bash
git clone https://github.com/Nico-AP/tiktok-metadata-kit
cd tiktok-metadata-kit
```

#### 2. Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

#### 3. Install Python dependencies

```bash
pip install -r requirements/base.txt
pip install -r requirements/dev.txt
```

#### 4. Install pre-commit hooks

```bash
pre-commit install
```

### Testing

Tests live at the project root in `tests/`, mirroring the package layout
(e.g. `tests/research_api/` covers `src/tiktok_metadata_kit/research_api/`).
They are not packaged into the distribution.

Run the full suite:

```bash
pytest
```

Run a single subpackage or file:

```bash
pytest tests/research_api/
pytest tests/research_api/test_retry.py -v
```

Coverage:

```bash
coverage run -m pytest
coverage report
```

#### How HTTP is mocked

The Research API client takes a `transport=` constructor argument so tests
can inject an `httpx.MockTransport` and drive the client without network
access or real credentials. The `MockHandler` helper in
`tests/research_api/conftest.py` records each request and returns programmed
responses in FIFO order — see existing tests for usage patterns.

No live API credentials are needed to run the suite.

#### Integration tests

Integration tests live in `tests/integration/` and hit the real TikTok
Research API. They are marked with `@pytest.mark.integration` and
**excluded from the default `pytest` run** so day-to-day development stays
fast and credential-free.

Run them explicitly:

```bash
pytest -m integration
```

They will skip (not fail) unless these env vars are set:

| Variable                       | Purpose                                  |
|--------------------------------|------------------------------------------|
| `TIKTOK_RESEARCH_API_KEY`      | Client key for the Research API.         |
| `TIKTOK_RESEARCH_API_SECRET`   | Client secret for the Research API.      |

##### Setting the env vars

**Inline, for a single invocation** (bash / zsh):

```bash
TIKTOK_RESEARCH_API_KEY=your-key \
TIKTOK_RESEARCH_API_SECRET=your-secret \
pytest -m integration
```

**Inline, for a single invocation** (Windows PowerShell):

```powershell
$env:TIKTOK_RESEARCH_API_KEY = "your-key"
$env:TIKTOK_RESEARCH_API_SECRET = "your-secret"
pytest -m integration
```

**Persistent for the current shell session** (bash / zsh):

```bash
export TIKTOK_RESEARCH_API_KEY=your-key
export TIKTOK_RESEARCH_API_SECRET=your-secret
```

**Persistent for the user** (Windows, PowerShell):

```powershell
[Environment]::SetEnvironmentVariable("TIKTOK_RESEARCH_API_KEY", "your-key", "User")
[Environment]::SetEnvironmentVariable("TIKTOK_RESEARCH_API_SECRET", "your-secret", "User")
```

Restart the shell after running these so the new values are picked up.

**From a `.env` file** — keep credentials out of shell history and out of the
repo. Create a project-local `.env` (already covered by `.gitignore`):

```
TIKTOK_RESEARCH_API_KEY=your-key
TIKTOK_RESEARCH_API_SECRET=your-secret
```

Load it before running pytest:

```bash
set -a; source .env; set +a    # bash / zsh
```

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') { $env:($matches[1].Trim()) = $matches[2].Trim() }
}
```

Note that integration tests consume API quota — keep them minimal and
favor `max_count=1` style probes for shape assertions.

## CI / Release

### Branching

| Branch  | Purpose                                                              |
|---------|----------------------------------------------------------------------|
| `main`  | Stable. Only ever advances when cutting a release. Each commit on `main` corresponds to a tagged version on PyPI. |
| `dev`   | Integration branch. Day-to-day work lands here via feature-branch PRs. |

Feature branches → PR → merge to `dev`. When ready to release: PR `dev` → `main`,
tag, release.

### Workflows

Three GitHub Actions workflows live in `.github/workflows/`:

| Workflow                      | Trigger                              | What it does                                                         |
|-------------------------------|--------------------------------------|----------------------------------------------------------------------|
| `test.yml`                    | push to `main`/`dev`; all PRs        | Runs `ruff check` and `pytest` with coverage (80% gate).             |
| `release-testpypi.yml`        | push of a tag matching `v*`          | Verifies the tag matches `pyproject.toml`, runs tests, builds sdist + wheel, publishes to **TestPyPI**. |
| `publish-pypi.yml`            | a GitHub Release is published        | Same checks and build, publishes to **production PyPI**.             |

Both release workflows use **trusted publishing** (OIDC) — no PyPI API tokens
are stored as GitHub Secrets.

### Cutting a release

The two-step flow lets you smoke-test the wheel on TestPyPI before promoting
it to production PyPI.

1. **Bump the version in `pyproject.toml`.** Follow [PEP 440](https://peps.python.org/pep-0440/) for prereleases
   (`1.2.0a1`, `1.2.0b1`, `1.2.0rc1`).
2. **Merge `dev` → `main`** via PR.
3. **Tag the release commit on `main`** and push the tag:

   ```bash
   git tag v1.2.0rc1
   git push --tags
   ```

   This fires `release-testpypi.yml`, which uploads to TestPyPI.

4. **Smoke-test the TestPyPI wheel:**

   ```bash
   pip install -i https://test.pypi.org/simple/ \
       --extra-index-url https://pypi.org/simple/ \
       --pre tiktok-metadata-kit==1.2.0rc1
   python -c "from tiktok_metadata_kit.research_api import ResearchAPIClient"
   ```

   (The `--extra-index-url` lets pip resolve regular dependencies from real
   PyPI; otherwise it only sees TestPyPI's smaller index.)

5. **Create a GitHub Release** on the tag (GitHub UI → Releases → "Draft a new release"
   → pick the tag → check "Set as a pre-release" for `aN`/`bN`/`rcN` versions).
   Publishing the Release fires `publish-pypi.yml`, which uploads to PyPI.

For a final (non-prerelease) release, repeat with a clean version
(`v1.2.0`) and leave the "pre-release" checkbox unchecked.

### Prereleases

PyPI accepts prerelease versions and `pip` ignores them by default. Users
who want them opt in with `--pre`:

```bash
pip install tiktok-metadata-kit --pre
```

Tag naming follows PEP 440: `v1.2.0a1` (alpha), `v1.2.0b1` (beta),
`v1.2.0rc1` (release candidate).

### First-time PyPI setup (one-off)

Trusted publishing requires a "pending publisher" to be registered on each
service before the first release:

- **TestPyPI:** https://test.pypi.org/manage/account/publishing/
- **PyPI:** https://pypi.org/manage/account/publishing/

For each, register:

| Field              | Value                                                         |
|--------------------|---------------------------------------------------------------|
| Project name       | `tiktok-metadata-kit`                                         |
| Owner              | `Nico-AP`                                                     |
| Repository         | `tiktok-metadata-kit`                                         |
| Workflow filename  | `release-testpypi.yml` (for TestPyPI) / `publish-pypi.yml` (for PyPI) |
| Environment name   | `testpypi` / `pypi`                                           |

Then create matching environments in the GitHub repo
(Settings → Environments). Optionally add required reviewers on the `pypi`
environment to gate production publishes behind manual approval.
