# Publishing DivApply to PyPI

This repo is set up for PyPI Trusted Publishing through GitHub Actions. No PyPI API token is needed.

## One-Time PyPI Setup

Create or sign in to a PyPI account, then add a trusted publisher for DivApply.

Use these values:

```text
PyPI project name: divapply
Owner: InnitDivine
Repository name: DivApply
Workflow filename: publish.yml
Environment name: pypi
```

If PyPI asks for the full workflow path, use:

```text
.github/workflows/publish.yml
```

## Release

Before tagging, run the local checks:

```powershell
.\tools\preflight.ps1
```

The preflight runs Ruff, pytest, package build, `twine check`, dependency audit, Docker build, and Docker selfcheck. If Docker is unavailable on the release machine, use `.\tools\preflight.ps1 -SkipDocker` and make sure the GitHub CI container job passes before tagging.

Update the version in both files:

```text
pyproject.toml
src/divapply/__init__.py
```

Add the same version section to:

```text
CHANGELOG.md
```

Commit the version change, then tag and push:

```bash
git tag v0.4.6
git push origin main
git push origin v0.4.6
```

The `Release` workflow will lint, test, build the package, verify the tag matches `pyproject.toml`, `src/divapply/__init__.py`, and `CHANGELOG.md`, publish to PyPI, and create a GitHub Release with the built artifacts. After the workflow succeeds, users can install with:

```bash
pip install "divapply[full]"
```

Before the next PyPI release, users can install the latest `main` directly from GitHub:

```bash
pip install "divapply[full] @ git+https://github.com/InnitDivine/DivApply.git"
```

## Verify

```bash
python -m pip install --upgrade "divapply[full]"
divapply --version
divapply doctor
```

The workflow only runs from `v*` tags, uses PyPI Trusted Publishing, and verifies that the tag matches both version files plus the changelog before publishing.
