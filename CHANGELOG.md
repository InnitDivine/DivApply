# Changelog

All notable changes to DivApply will be documented here.

## 0.4.0

- Renamed the project from ApplyPilot to DivApply.
- Moved the Python package to `src/divapply/`.
- Kept the public CLI entry point as `divapply`.
- Added a Windows bootstrap install flow for fresh GitHub clones.
- Added legacy migration support for previous `~/.applypilot` data.
- Added hidden coursework storage for profile matching.
- Added one-page resume shaping and tighter PDF layout defaults.

## 0.4.1

- Fixed the GitHub Actions PyPI publish workflow so it requests repository contents access before checkout.
- Kept the DivApply release/docs branding aligned with the Codex-assisted development disclosure.

## 0.4.2

- Added a PyPI trusted-publishing workflow for `pip install divapply` releases.
- Reworked the README around the simple pip-first install path.
- Kept the GitHub clone installers as fallback/development options.

## 0.4.3

- Fixed neutral job scoring edge cases for preferred qualifications and hard requirement gaps.
- Kept company and source/job-board fields separate in scoring, apply prompts, logs, traces, and exports.
- Fixed ultimate resume job selection to prioritize highest fit scores before recency.
- Hardened resume and cover letter HTML escaping for generated PDFs.
- Added regression coverage for scoring, apply prompt context, PDF template output, and safe exports.

## Unreleased

- Future work will continue under the DivApply branding.
