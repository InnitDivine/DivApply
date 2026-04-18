# DivApply

DivApply is an AI-assisted job application pipeline that discovers jobs, enriches postings, scores fit, tailors resumes, writes cover letters, and can optionally drive browser-based applications.

It is designed to stay fact-driven: it uses your profile, resume, saved preferences, and private coursework knowledge to make matching decisions without inventing experience.

For transparency about the AI-assisted development process, see [AI_ASSISTANCE.md](AI_ASSISTANCE.md).

## What It Does

DivApply runs in stages:

1. Discover jobs from configured boards and direct sources.
2. Enrich postings with full descriptions and application URLs.
3. Score jobs against your profile and resume.
4. Tailor a resume per job.
5. Generate a cover letter per job.
6. Export PDFs and, if enabled, launch browser-based auto-apply.

## Main Parts

- `src/divapply/discovery/` handles job discovery.
- `src/divapply/enrichment/` expands short listings into full job descriptions.
- `src/divapply/scoring/` scores jobs, tailors resumes, writes cover letters, and produces PDFs.
- `src/divapply/apply/` handles browser automation and form filling.
- `src/divapply/database.py` stores jobs and hidden coursework knowledge.
- `src/divapply/config.py` loads profile, search config, and runtime paths.

## Install

### Quick install from GitHub

1. Install Git.
2. Install the official Python 3.11+ release from [python.org](https://www.python.org/downloads/).
3. Clone the repo and run the bootstrap script:

```powershell
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
.\tools\bootstrap.ps1
```

That script creates a local `.venv`, installs DivApply, and runs `divapply doctor` for you.

If you want an editable development setup, use:

```powershell
.\tools\bootstrap.ps1 -Dev
```

### If `python` is not on PATH

If Windows cannot find `python` or `py`, point the bootstrap script at a full interpreter path:

```powershell
.\tools\bootstrap.ps1 -PythonCommand "C:\Path\To\python.exe"
```

### Manual install

If you already have a working Python 3.11+ environment:

```powershell
pip install .
```

For editable development:

```powershell
pip install -e .
```

After installing, run:

```powershell
divapply doctor
```

That checks your profile files, LLM setup, browser runtime, and apply backend.

If you are upgrading from a previous release, run:

```powershell
divapply migrate
```

That copies your old local files into the new `~/.divapply` layout.

## First Run

```bash
divapply init
```

This creates your profile, resume, search config, and environment file under your local app data directory.

## Common Commands

```bash
divapply run
divapply run discover enrich
divapply run score tailor cover
divapply apply
divapply apply --dry-run
divapply status
divapply dashboard
divapply import-coursework path\to\transcript.json
divapply migrate
```

## Configuration

DivApply reads local user data from your app directory:

- `profile.json` for personal details, work history, and preferences
- `resume.txt` for the base resume
- `searches.yaml` for search terms and locations
- `.env` for API keys and runtime settings
- `divapply.db` for jobs and coursework knowledge

## Coursework Knowledge

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
python -m py_compile src/divapply/**/*.py
```

## Notes

- The codebase uses the `divapply` Python package.
- The primary public branding and CLI entry point is `DivApply`.
- Migration notes and legacy compatibility items live in [MIGRATION_CHECKLIST.md](MIGRATION_CHECKLIST.md).
- Auto-apply on a fresh machine usually needs Node.js `npx` plus Playwright browser binaries. If Firefox is missing, run `npx playwright install firefox` once before using `divapply apply`.
- Browser-based auto-apply can be risky. Use dry runs and review the generated prompt files if you are testing a new setup.
