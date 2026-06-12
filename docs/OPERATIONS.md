# DivApply Operations

DivApply is a local-first CLI. Production risk mostly comes from packaging, user-data handling, and unattended browser automation rather than server infrastructure.

## CI/CD

CI runs on pull requests, pushes to `main`, and manual dispatch. It verifies:

- Ruff across the repo
- Pytest on Python 3.11, 3.12, and 3.13
- Source distribution and wheel build
- Package metadata with `twine check`
- Docker image build and CLI smoke checks

Publishing runs only on `v*` tags. Tag releases are blocked when the tag version does not match `pyproject.toml`, `src/divapply/__init__.py`, and `CHANGELOG.md`. A successful release publishes to PyPI and creates a matching GitHub Release with the built artifacts.

## Docker

The container is for repeatable CLI execution and smoke testing.

```bash
docker build -t divapply .
docker run --rm -v "$HOME/.divapply:/data" divapply doctor
docker run --rm -v "$HOME/.divapply:/data" divapply run discover enrich
```

The image uses `DIVAPPLY_DIR=/data` and runs as a non-root user. User data, databases, logs, generated documents, `.env`, and credentials are excluded by `.dockerignore`; mount them at runtime instead.

## Deployment

For PyPI releases:

1. Run `python -m pytest -q` and `ruff check .`.
2. Update the version in `pyproject.toml` and `src/divapply/__init__.py`.
3. Add the same version section to `CHANGELOG.md`.
4. Commit the version change.
5. Tag with the same version, for example `git tag v0.4.6`.
6. Push `main`, then push the tag.
7. Verify the GitHub `Release` workflow, GitHub Release page, and published PyPI wheel in a clean environment.

Clean install smoke test:

```bash
python -m venv .venv-install-smoke
. .venv-install-smoke/bin/activate
python -m pip install --upgrade pip
python -m pip install "divapply[full]"
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
```

Keep secret-inclusive archives encrypted and out of git.
