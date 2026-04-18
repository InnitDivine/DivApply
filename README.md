# DivApply

DivApply is an AI-assisted job application pipeline that discovers jobs, enriches postings, scores fit, tailors resumes, writes cover letters, and can optionally drive browser-based applications.

It is designed to stay fact-driven: it uses your profile, resume, saved preferences, and private coursework knowledge to make matching decisions without inventing experience.

For transparency about the AI-assisted development process, see [AI_ASSISTANCE.md](AI_ASSISTANCE.md).

## What it does

DivApply runs in stages:

1. Discover jobs from configured boards and direct sources.
2. Enrich postings with full descriptions and application URLs.
3. Score jobs against your profile and resume.
4. Tailor a resume per job.
5. Generate a cover letter per job.
6. Export PDFs and, if enabled, launch browser-based auto-apply.

## Main parts

- `src/applypilot/discovery/` handles job discovery.
- `src/applypilot/enrichment/` expands short listings into full job descriptions.
- `src/applypilot/scoring/` scores jobs, tailors resumes, writes cover letters, and produces PDFs.
- `src/applypilot/apply/` handles browser automation and form filling.
- `src/applypilot/database.py` stores jobs and hidden coursework knowledge.
- `src/applypilot/config.py` loads profile, search config, and runtime paths.

## Install

```bash
pip install .
```

If you want an editable install during development:

```bash
pip install -e .
```

The package exposes both `divapply` and `applypilot` commands for compatibility.

## First run

```bash
divapply init
```

This creates your profile, resume, search config, and environment file under your local app data directory.

## Common commands

```bash
divapply run
divapply run discover enrich
divapply run score tailor cover
divapply apply
divapply apply --dry-run
divapply status
divapply dashboard
divapply import-coursework path\to\transcript.json
```

If you prefer the old command name, the same commands also work with `applypilot`.

## Configuration

DivApply reads local user data from your app directory:

- `profile.json` for personal details, work history, and preferences
- `resume.txt` for the base resume
- `searches.yaml` for search terms and locations
- `.env` for API keys and runtime settings
- `applypilot.db` for jobs and coursework knowledge

## Coursework knowledge

DivApply can keep transcript and coursework information in a hidden local database. That knowledge is used to improve matching and reasoning, but it is not copied into your resume or cover letter unless that information already belongs there.

You can add coursework with:

```bash
divapply import-coursework path\to\file.json
```

Supported import formats:

- JSON
- CSV
- plain text
- PDF transcripts if `pypdf` is installed

## Build

```bash
hatch build
```

Or, if you just want a quick local verification:

```bash
python -m py_compile src/applypilot/**/*.py
```

## Notes

- The codebase keeps the internal Python package name `applypilot` for compatibility.
- The primary public branding and CLI entry point is `DivApply`.
- Browser-based auto-apply can be risky. Use dry runs and review the generated prompt files if you are testing a new setup.
