# DivApply Migration Notes

This file tracks the remaining work to finish the transition from the older ApplyPilot codebase to the current DivApply release.

## 0.5.1 Security Migration

- Stop using the removed `divapply[jobspy-upstream]` compatibility extra; it could select vulnerable Markdownify metadata.
- Install `divapply[full]` first, then install the exact hash-verified JobSpy wheel with `--no-deps`.
- Run `python -m divapply.jobspy_runtime` after installation; only the intentional secure Markdownify override may differ from JobSpy's upstream metadata.

## Completed

- [x] Public branding switched to `DivApply`.
- [x] Installable Python package renamed to `divapply`.
- [x] CLI entry point renamed to `divapply`.
- [x] Legacy `~/.applypilot` data files are still readable.
- [x] Legacy `applypilot.db` is still readable if it exists.
- [x] `divapply migrate` copies legacy files into the new `~/.divapply` layout.
- [x] Fresh-install and legacy-upgrade migration tests exist.
- [x] Fresh-install bootstrap guidance is documented for Windows users.
- [x] Public docs now use `DivApply` branding for install guidance.

## Still To Do

- None.

## Validation Note

The repository-side install path is now guarded by `tools/bootstrap.ps1`, which expects a stock Python 3.11+ build. The local Windows environment on this machine only exposed vendor Python installs that were missing standard-library modules, so the bootstrap script is designed to fail fast with a clear message in that case.

## Legacy Paths To Preserve During Migration

- `~/.applypilot/profile.json`
- `~/.applypilot/searches.yaml`
- `~/.applypilot/.env`
- `~/.applypilot/applypilot.db`
- `APPLYPILOT_DIR`
- `APPLYPILOT_APPLY_BACKEND`
- `APPLYPILOT_BROWSER`

## Validation Targets

- `pip install ".[full]"`
- `pip install -e ".[dev,full]"`
- `pip install --no-deps "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"`
- `python -m divapply.jobspy_runtime`
- `divapply --version`
- `python -m divapply --version`
- `divapply init`
- `divapply status`
- `divapply doctor`
- `divapply run --dry-run`
- `divapply apply --dry-run`
