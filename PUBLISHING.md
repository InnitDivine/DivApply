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

Update the version in both files:

```text
pyproject.toml
src/divapply/__init__.py
```

Commit the version change, then tag and push:

```bash
git tag v0.4.2
git push origin main
git push origin v0.4.2
```

The `Publish to PyPI` workflow will build the package and publish it. After the workflow succeeds, users can install with:

```bash
pip install divapply
```

## Verify

```bash
python -m pip install --upgrade divapply
divapply --version
divapply doctor
```
