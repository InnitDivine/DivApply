# DivApply

DivApply is an AI-assisted job application pipeline that discovers jobs, enriches postings, scores fit, tailors resumes, writes cover letters, and can optionally drive browser-based applications.

It is designed to stay fact-driven: it uses your profile, resume, saved preferences, and private coursework knowledge to make matching decisions without inventing experience.

For transparency about the Codex-assisted development process, see [AI_ASSISTANCE.md](AI_ASSISTANCE.md).

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

### Quick Install

Once DivApply is published to PyPI:

```bash
pip install divapply
pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex
python -m playwright install chromium firefox
divapply init              # one-time setup: resume, profile, preferences, API keys
divapply doctor            # verify setup and show what's missing
divapply run               # discover > enrich > score > tailor > cover letters
divapply run -w 4          # same but parallel
divapply apply             # autonomous browser-driven submission
divapply apply -w 3        # parallel apply workers
divapply apply --dry-run   # fill forms without submitting
```

Before the first PyPI release is published, install directly from GitHub:

```bash
pip install git+https://github.com/InnitDivine/DivApply.git
pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex
python -m playwright install chromium firefox
```

Why the second install command? `python-jobspy` pins an exact NumPy version in its metadata that can fight pip's resolver. Installing JobSpy with `--no-deps`, then installing its real runtime dependencies separately, avoids that resolver trap.

`divapply apply` also needs Node.js 18+ for `npx` and either the Codex CLI or Claude Code CLI.

### Clone Install

Use this if you want a local checkout, development setup, or the all-in-one installer.

Windows Command Prompt:

```bat
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
install
```

PowerShell:

```powershell
.\install.ps1
```

macOS/Linux:

```bash
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
bash ./install.sh
```

The clone installer creates a local `.venv`, installs DivApply, installs JobSpy support, downloads Playwright browsers, prepares `~/.divapply`, and runs `divapply doctor`.

### Installer Options

Windows Command Prompt:

```bat
install -Dev              # editable install with test/lint tools
install -Init             # run divapply init after installing
install -Recreate         # rebuild the .venv from scratch
install -SkipBrowsers     # skip Playwright browser downloads
install -SkipJobSpy       # skip python-jobspy
install -Browsers all     # install chromium, firefox, and webkit
install -Help             # show installer help
```

PowerShell:

```powershell
.\install.ps1 -Dev
.\install.ps1 -Init
.\install.ps1 -Recreate
.\install.ps1 -SkipBrowsers
.\install.ps1 -SkipJobSpy
.\install.ps1 -Browsers all
.\install.ps1 -Help
```

macOS/Linux:

```bash
bash ./install.sh --dev
bash ./install.sh --init
bash ./install.sh --recreate
bash ./install.sh --skip-browsers
bash ./install.sh --skip-jobspy
bash ./install.sh --browsers all
bash ./install.sh --python /path/to/python3.11
```

### Publishing To PyPI

This repo includes a GitHub Actions workflow for PyPI Trusted Publishing. See [PUBLISHING.md](PUBLISHING.md) for the one-time PyPI setup and release commands.

### Manual Local Install

If you already have a working Python 3.11+ environment:

```powershell
pip install ".[full]"
pip install --no-deps python-jobspy
python -m playwright install chromium firefox
```

For editable development:

```powershell
pip install -e ".[dev,full]"
pip install --no-deps python-jobspy
python -m playwright install chromium firefox
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
- Auto-apply on a fresh machine needs Node.js `npx`, an apply agent CLI such as Codex or Claude Code, and Playwright browser binaries. The installer downloads the browser binaries; rerun `.\install.ps1 -Browsers firefox` if Firefox is missing.
- Browser-based auto-apply can be risky. Use dry runs and review the generated prompt files if you are testing a new setup.
