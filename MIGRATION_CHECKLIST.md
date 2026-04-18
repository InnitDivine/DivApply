# DivApply Migration Checklist

This file tracks the remaining work to finish the transition from the older ApplyPilot codebase to the current DivApply release.

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

- `pip install .`
- `pip install -e .`
- `divapply init`
- `divapply status`
- `divapply doctor`
- `divapply run --dry-run`
- `divapply apply --dry-run`
