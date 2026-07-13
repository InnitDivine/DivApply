# DivApply Operations

DivApply is a local-first CLI. Production risk mostly comes from packaging, user-data handling, and unattended browser automation rather than server infrastructure.

## CI/CD

CI runs on pull requests, pushes to `main`, and manual dispatch. It verifies:

- Ruff across the repo
- Mypy for Linux and Windows code paths
- Full Python 3.12 tests, Ruff, mypy, and `divapply.cmd` smoke on native `windows-latest`
- Branch coverage with a 50% minimum
- Pytest on Python 3.11, 3.12, and 3.13
- Exact Python resolution from `uv.lock` with `uv==0.11.28`
- Python audit with `pip-audit` and locked MCP audit with `npm audit`
- Immutable full-SHA GitHub Action references and exact Node.js 24.18.0 provisioning
- Source distribution and wheel build
- Package metadata with `twine check`
- Clean wheel install smoke checks for both `divapply` and `python -m divapply`
- Docker image build and CLI smoke checks

CI and release verification/build jobs use read-only repository permissions and disable persisted checkout credentials. Release builds once, uploads the verified distribution, then artifact-only promotion jobs separate PyPI `id-token: write` from GitHub Release `contents: write`; neither privileged job checks out or executes repository build code. Jobs have timeouts so hung tests, builds, audits, or Docker commands do not block the pipeline indefinitely.

Publishing runs only on `v*` tags. Tag releases are blocked when the tagged commit is not already reachable from `main`, or when the tag version does not match `pyproject.toml`, `src/divapply/__init__.py`, and `CHANGELOG.md`. The release workflow runs a pre-publish lint/test gate, builds once under read-only permissions, emits a locked CycloneDX 1.5 SBOM and SHA256 manifest, attests those checksum subjects in a no-checkout job, and promotes the same verified package files to PyPI and a matching GitHub Release.

Dependabot opens weekly PRs for GitHub Actions, Python packaging, the bundled npm lock, and Docker image digests so CI/CD drift is visible before a release window.

Run the local preflight before tagging:

```powershell
.\tools\preflight.ps1
```

Use `-SkipDocker` only when Docker is unavailable on the release machine. Use `-SkipAudit` only for a temporary PyPI advisory outage and rerun the audit before publishing.

Preflight requires `uv==0.11.28`, Node.js/npm, and the checked-in Python/npm locks. It syncs the locked environment, runs both mypy platform targets, enforces branch coverage, builds without isolation from the locked Hatchling version, and audits both dependency ecosystems.

## Docker

The container is for repeatable CLI execution and smoke testing. Both the Python base and uv tool image use immutable manifest digests; application dependencies come from `uv.lock`, and JobSpy uses an exact wheel URL plus SHA256.

```bash
docker build -t divapply .
docker run --rm -v "$HOME/.divapply:/data" divapply doctor
docker run --rm -v "$HOME/.divapply:/data" divapply run discover enrich
```

The image uses `DIVAPPLY_DIR=/data` and runs as a non-root user. User data, databases, logs, generated documents, `.env`, and credentials are excluded by `.dockerignore`; mount them at runtime instead.

The image includes Open Containers metadata labels and a Docker health check that runs `divapply selfcheck` against the mounted data directory. Inspect health details with:

```bash
docker inspect --format '{{json .State.Health}}' CONTAINER_ID
```

## Deployment

For PyPI releases:

1. Run `python -m pytest -q` and `ruff check .`.
2. Run `.\tools\preflight.ps1`.
3. Update the version in `pyproject.toml` and `src/divapply/__init__.py`.
4. Add the same version section to `CHANGELOG.md`.
5. Commit the version change.
6. Merge or fast-forward the release commit onto `main`.
7. Tag the `main` commit with the same version, for example `git tag v0.5.0`.
8. Push `main`, then push the tag.
9. Verify the GitHub `Publish release` workflow, GitHub Release page, and published PyPI wheel in a clean environment.

Clean install smoke test:

```bash
python -m venv .venv-install-smoke
. .venv-install-smoke/bin/activate
python -m pip install --upgrade pip
python -m pip install "divapply[full]"
python -m pip install --no-deps python-jobspy==1.1.82
python -c "import jobspy"
divapply --version
python -m divapply --version
divapply selfcheck
```

The clean install smoke test intentionally installs `python-jobspy` with `--no-deps` after `divapply[full]`. Upstream `python-jobspy` 1.1.82 still pins `markdownify<0.14.0`, while DivApply's secure runtime dependency floor requires `markdownify>=0.14.1`.

## Monitoring And Logging

Local health checks:

```bash
divapply selfcheck
divapply doctor
divapply status
```

Runtime artifacts live under `~/.divapply` by default. Generated logs stay under `~/.divapply/logs`, use user-only permissions, and expire after 30 days during normal command startup. Override the TTL with `DIVAPPLY_LOG_RETENTION_DAYS` from `0` (retain indefinitely) through `3650`. Export files redact application errors before sharing.

For scheduled or unattended runs, capture command output to a dated log file and review non-zero exits:

```bash
mkdir -p ~/.divapply/logs
divapply run discover enrich >> ~/.divapply/logs/run-$(date -u +%Y%m%dT%H%M%SZ).log 2>&1
```

In containers, keep stdout/stderr attached to the container runtime and mount `/data` to durable storage. The health check validates imports, directories, database initialization, and search-config shape without contacting job boards, LLMs, browsers, or apply agents.

## LLM request budgets

LLM calls default to three attempts and a 600-second total caller budget. HTTP connect, read, write, and pool timeouts are configured separately, and provider `Retry-After` values are rejected when negative/non-finite and capped at 60 seconds. Override `DIVAPPLY_LLM_CONNECT_TIMEOUT`, `DIVAPPLY_LLM_READ_TIMEOUT`, `DIVAPPLY_LLM_WRITE_TIMEOUT`, `DIVAPPLY_LLM_POOL_TIMEOUT`, `DIVAPPLY_LLM_MAX_ATTEMPTS`, `DIVAPPLY_LLM_TOTAL_TIMEOUT`, `DIVAPPLY_LLM_RETRY_BASE_DELAY`, or `DIVAPPLY_LLM_RETRY_MAX_DELAY` in `~/.divapply/.env`. Invalid or out-of-range values fail at client creation instead of creating an unbounded run.

## Recovery

Create a local recovery archive:

```bash
divapply backup
```

By default, backups include profile, resume, searches, answer bank, database, local config, generated resumes, and cover letters. Logs, `.env`, and `credentials.yaml` are excluded unless explicitly requested:

```bash
divapply backup --include-logs
divapply backup --include-secrets
divapply backup --include-logs --include-secrets
```

`--include-logs` still excludes prompt and MCP files unless `--include-secrets` is also present. Store any log- or secret-inclusive archive encrypted and outside Git.

Restore by extracting the archive into the target DivApply app directory, then run:

```bash
divapply selfcheck
divapply doctor
divapply status
```

After restore, confirm `divapply.db`, `profile.json`, `resume.txt`, and `searches.yaml` exist in the target app directory and that generated output directories are present if you restored them. Keep secret-inclusive archives encrypted and out of git.
