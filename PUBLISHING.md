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

The preflight validates `uv.lock`, syncs exact dependencies, runs Ruff, Linux/Windows mypy, branch-covered pytest, package build, `twine check`, Python/npm audits, Docker build, and Docker selfcheck. If Docker is unavailable on the release machine, use `.\tools\preflight.ps1 -SkipDocker` and make sure the GitHub CI container job passes before tagging.

Update the version in both files:

```text
pyproject.toml
src/divapply/__init__.py
```

Add the same version section to:

```text
CHANGELOG.md
```

Commit the version change, merge or fast-forward it onto `main`, then tag and push:

```bash
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z
```

The `Publish release` workflow will lint, test, verify the tagged commit is the current `main` tip, verify the tag matches `pyproject.toml`, `src/divapply/__init__.py`, and `CHANGELOG.md`, and build the package once under read-only permissions. Separate no-checkout promotion jobs download that verified artifact: one owns only PyPI Trusted Publishing authority, and the other owns only GitHub Release authority. After the workflow succeeds, users can install with:

```bash
pip install "divapply[full]"
python -m pip install --no-deps "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"
```

`python-jobspy` is installed with `--no-deps` because upstream version 1.1.82 still pins `markdownify<0.14.0`, while DivApply's secure full extra requires `markdownify>=0.14.1` for CVE-2025-46656. Do not move `python-jobspy` into the `full` extra or remove the no-deps release smoke test until upstream relaxes that pin and `pip-audit` passes without ignores.

For development snapshots, users can install the latest `main` directly from GitHub:

```bash
pip install "divapply[full] @ git+https://github.com/InnitDivine/DivApply.git"
python -m pip install --no-deps "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"
```

## Verify

```bash
python -m pip install --upgrade "divapply[full]"
python -m pip install --no-deps "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"
python -m divapply.jobspy_runtime
divapply --version
python -m divapply --version
divapply doctor
```

The workflow only runs from `v*` tags, uses PyPI Trusted Publishing, and verifies that the tag matches both version files plus the changelog before publishing.
