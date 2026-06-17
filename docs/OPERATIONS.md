# DivApply Operations

DivApply is a local-first CLI. Production risk mostly comes from packaging, user-data handling, and unattended browser automation rather than server infrastructure.

## CI/CD

CI runs on pull requests, pushes to `main`, and manual dispatch. It verifies:

- Ruff across the repo
- Pytest on Python 3.11, 3.12, and 3.13
- Dependency audit with `pip-audit`
- Source distribution and wheel build
- Package metadata with `twine check`
- Docker image build and CLI smoke checks

CI and release jobs use explicit read-only repository permissions except for the publish step, which grants only the `contents: write` and `id-token: write` permissions needed for GitHub Releases and PyPI Trusted Publishing. Jobs have timeouts so hung tests, builds, audits, or Docker commands do not block the pipeline indefinitely.

Publishing runs only on `v*` tags. Tag releases are blocked when the tagged commit is not already reachable from `main`, or when the tag version does not match `pyproject.toml`, `src/divapply/__init__.py`, and `CHANGELOG.md`. The release workflow also runs a pre-publish lint and test gate before building or uploading artifacts. A successful release publishes to PyPI and creates a matching GitHub Release with the built artifacts.

Dependabot opens weekly PRs for GitHub Actions and Python packaging dependencies so CI/CD drift is visible before a release window.

Run the local preflight before tagging:

```powershell
.\tools\preflight.ps1
```

Use `-SkipDocker` only when Docker is unavailable on the release machine. Use `-SkipAudit` only for a temporary PyPI advisory outage and rerun the audit before publishing.

## Docker

The container is for repeatable CLI execution and smoke testing.

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
7. Tag the `main` commit with the same version, for example `git tag v0.4.6`.
8. Push `main`, then push the tag.
9. Verify the GitHub `Release` workflow, GitHub Release page, and published PyPI wheel in a clean environment.

Clean install smoke test:

```bash
python -m venv .venv-install-smoke
. .venv-install-smoke/bin/activate
python -m pip install --upgrade pip
python -m pip install "divapply[full]"
python -m pip install --no-deps python-jobspy
python -c "import jobspy"
divapply --version
divapply selfcheck
```

## Monitoring And Logging

Local health checks:

```bash
divapply selfcheck
divapply doctor
divapply status
```

Runtime artifacts live under `~/.divapply` by default. Generated logs should stay under `~/.divapply/logs`; export files redact application errors before sharing.

For scheduled or unattended runs, capture command output to a dated log file and review non-zero exits:

```bash
mkdir -p ~/.divapply/logs
divapply run discover enrich >> ~/.divapply/logs/run-$(date -u +%Y%m%dT%H%M%SZ).log 2>&1
```

In containers, keep stdout/stderr attached to the container runtime and mount `/data` to durable storage. The health check validates imports, directories, database initialization, and search-config shape without contacting job boards, LLMs, browsers, or apply agents.

## Recovery

Create a local recovery archive:

```bash
divapply backup
```

By default, backups include profile, resume, searches, answer bank, database, local config, generated resumes, cover letters, and logs. `.env` and `credentials.yaml` are excluded unless explicitly requested:

```bash
divapply backup --include-secrets
```

Restore by extracting the archive into the target DivApply app directory, then run:

```bash
divapply selfcheck
divapply doctor
divapply status
```

After restore, confirm `divapply.db`, `profile.json`, `resume.txt`, and `searches.yaml` exist in the target app directory and that generated output directories are present if you restored them. Keep secret-inclusive archives encrypted and out of git.
