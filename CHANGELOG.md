# Changelog

All notable changes to DivApply will be documented here.

## Unreleased

- Future work will continue under the DivApply branding.

## 0.4.7

- Fixed interactive dashboard description loading after the lazy-rendering optimization.
- Preserved dashboard performance improvements while keeping static dashboards read-only.

## 0.4.6

- Removed the legacy one-off targeted resume command and module.
- Kept resume generation focused on the main `run tailor cover pdf` pipeline.

## 0.4.5

- Fixed fresh-install database startup by creating the database parent directory before opening SQLite.
- Added regression coverage for clean-home database initialization, matching GitHub Actions behavior.

## 0.4.4

- Added `divapply edit` as the local browser setup editor for profile and search configuration.
- Simplified profile/search examples around no-password profile data and tiered search queries.
- Preserved rich profile fields when saving through the editor, including references, certifications, and education metadata.
- Improved scoring/search setup compatibility for simple `skills`, preferred roles, and ApplyPilot-style search YAML.
- Added dashboard/accessibility, discovery, enrichment, Workday, SmartExtract, scoring, and editor regression coverage.
- Cleaned root documentation by moving migration and AI disclosure notes under `docs/`.

## 0.4.3

- Fixed neutral job scoring edge cases for preferred qualifications and hard requirement gaps.
- Kept company and source/job-board fields separate in scoring, apply prompts, logs, traces, and exports.
- Fixed one-off targeted resume job selection to prioritize highest fit scores before recency.
- Hardened resume and cover letter HTML escaping for generated PDFs.
- Added regression coverage for scoring, apply prompt context, PDF template output, and safe exports.

## 0.4.2

- Added a PyPI trusted-publishing workflow for `pip install divapply` releases.
- Reworked the README around the simple pip-first install path.
- Kept the GitHub clone installers as fallback/development options.

## 0.4.1

- Fixed the GitHub Actions PyPI publish workflow so it requests repository contents access before checkout.
- Kept the DivApply release/docs branding aligned with the Codex-assisted development disclosure.

## 0.4.0

- Renamed the project from ApplyPilot to DivApply.
- Moved the Python package to `src/divapply/`.
- Kept the public CLI entry point as `divapply`.
- Added a Windows bootstrap install flow for fresh GitHub clones.
- Added legacy migration support for previous `~/.applypilot` data.
- Added hidden coursework storage for profile matching.
- Added one-page resume shaping and tighter PDF layout defaults.
