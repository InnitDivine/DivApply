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

### Python Version

Use Python 3.12 for the full DivApply setup.

DivApply core supports Python 3.11+, but full job-board discovery uses `python-jobspy`, and JobSpy currently pins `numpy==1.26.3`. That NumPy pin can fail on newer Python releases such as Python 3.13 and Python 3.14. If you want JobSpy-backed discovery, use Python 3.11 or 3.12; Python 3.12 is recommended.

Avoid Python 3.13/3.14 for the full setup until JobSpy updates its dependency pins.

Windows example:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
```

macOS/Linux example:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### Quick Install

Once DivApply is published to PyPI:

```bash
pip install divapply
pip install --no-deps python-jobspy
pip install "numpy==1.26.3" "pandas>=2.1,<3.0" "markdownify>=0.13.1,<0.14.0" "regex>=2024.4.28,<2025.0.0" pydantic tls-client requests
python -m playwright install chromium firefox
divapply init              # one-time setup: resume, profile, preferences, API keys
divapply doctor            # verify setup and show what's missing
divapply run               # discover > enrich > score > tailor > cover letters
divapply run -w 4          # same but parallel
divapply apply --dry-run   # browser test without final submit
divapply apply --yes       # confirmed autonomous browser-driven submission
divapply apply -w 3        # parallel apply workers
divapply selfcheck         # offline local sanity check
```

Before the first PyPI release is published, install directly from GitHub:

```bash
pip install git+https://github.com/InnitDivine/DivApply.git
pip install --no-deps python-jobspy
pip install "numpy==1.26.3" "pandas>=2.1,<3.0" "markdownify>=0.13.1,<0.14.0" "regex>=2024.4.28,<2025.0.0" pydantic tls-client requests
python -m playwright install chromium firefox
```

Why the separate JobSpy install commands? `python-jobspy` pins an exact NumPy version in its metadata. Installing JobSpy with `--no-deps`, then installing the compatible runtime pins separately, avoids resolver conflicts and makes Python-version problems obvious.

`divapply apply` also needs Node.js 18+ for `npx` and either the Codex CLI or Claude Code CLI.

Privacy details live in [docs/PRIVACY.md](docs/PRIVACY.md).

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
bash ./install.sh --python /path/to/python3.12
```

The installer accepts Python 3.11+ for core DivApply. If JobSpy is enabled, it requires Python 3.11 or 3.12 and will stop early on newer Python versions with a clear message.

### Publishing To PyPI

This repo includes a GitHub Actions workflow for PyPI Trusted Publishing. See [PUBLISHING.md](PUBLISHING.md) for the one-time PyPI setup and release commands.

### Manual Local Install

If you already have a working Python 3.12 environment:

```powershell
pip install ".[full]"
pip install --no-deps python-jobspy
pip install "numpy==1.26.3" "pandas>=2.1,<3.0" "markdownify>=0.13.1,<0.14.0" "regex>=2024.4.28,<2025.0.0"
python -m playwright install chromium firefox
```

For editable development:

```powershell
pip install -e ".[dev,full]"
pip install --no-deps python-jobspy
pip install "numpy==1.26.3" "pandas>=2.1,<3.0" "markdownify>=0.13.1,<0.14.0" "regex>=2024.4.28,<2025.0.0"
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
divapply coursework-summary
divapply export jobs --out jobs.csv
divapply explain https://example.com/job
divapply track screening https://example.com/job --follow-up 2026-05-15
divapply followups
divapply answers add "Years of Python?" "2 years."
divapply selfcheck
divapply migrate
```

## Master Resume Workflow

Treat `~/.divapply/resume.txt` as the master resume. Keep it broad, truthful, and complete enough to cover real work history, projects, skills, education, and certifications. DivApply never treats tailored resumes as new facts; each generated resume is a job-specific view of the master resume plus profile data and hidden coursework summaries.

Recommended loop:

1. Update `resume.txt` and `profile.json` with only verified facts.
2. Run `divapply run score tailor --validation strict` for high-risk roles or `--validation normal` for daily use.
3. Review generated resumes and reports in `~/.divapply/tailored_resumes/`.
4. Convert/export only after factuality and coherence checks pass.

Validation modes:

- `strict`: banned wording, structure issues, fabrication, and judge failures block output.
- `normal`: banned wording warns; fabrication and structure issues block output.
- `lenient`: skips style strictness and LLM judge, but keeps core fabrication checks.
- `none`: skips validation; use only for debugging.

Tailoring rules:

- Never invent jobs, employers, credentials, licenses, degrees, skills, coursework, tools, dates, or metrics.
- Rephrase and emphasize only truthful material already in `resume.txt`, `profile.json`, or hidden coursework summaries.
- Coursework can influence matching/tailoring decisions, but it is not copied into resumes unless it already belongs in the resume.

## Scoring Transparency

Scoring is hybrid: keyword hit-rate + local hashed embedding similarity + the existing LLM judgment. Default weights are 30% keyword, 30% embedding, 40% LLM.

Scoring stores safe, human-readable fields:

- `fit_score`
- `llm_score`
- `keyword_score`
- `embedding_score`
- `composite_score`
- `score_breakdown`
- `score_reasoning`
- `matched_skills`
- `missing_skills`
- `keyword_hits`
- `risk_flags`
- `apply_or_skip_reason`

Use `divapply explain JOB_URL` to view the breakdown for one job. Existing legacy rows show missing hybrid fields until you run `divapply rescore`. Tailoring reads score gaps as targets, but only addresses a gap when the master resume/profile already supports it.

Status/export commands do not print full private resume, profile, transcript, or database text.

Stage-specific LLM aliases are supported:

```bash
DIVAPPLY_LLM_SCORER=openai:gpt-5.4-mini
DIVAPPLY_LLM_TAILOR=ollama:qwen2.5:14b
DIVAPPLY_LLM_JUDGE=gemini:gemini-2.0-flash
```

Old `LLM_MODEL_SCORE`, `LLM_MODEL_TAILOR`, and `LLM_MODEL_COVER` variables still work.

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
divapply coursework-summary
```

Supported import formats:

- JSON
- CSV
- plain text
- PDF transcripts if `pypdf` is installed

`divapply coursework-summary` shows only row count, schools, subject areas, inferred skills, and import sources. It never dumps transcript text.

## Search Filters

`searches.yaml` supports safe filters:

```yaml
filters:
  company_blacklist:
    - "Example Staffing"
  title_blacklist:
    - "intern"
  required_keywords:
    - "python"
  excluded_keywords:
    - "clearance"
  remote_preference: "remote"  # any, remote, hybrid, onsite
```

Older keys still work: `exclude_titles`, `title_blacklist`, `company_blacklist`, `required_keywords`, `excluded_keywords`, and `remote_preference`.

## Export And Tracking

Export safe job tracking fields:

```bash
divapply export jobs --out jobs.csv
divapply export jobs --out jobs.json --format json
```

Exported columns: title, site, url, application_url, fit_score, apply_status, discovered_at, scored_at, tailored_at, applied_at, and a redacted apply_error snippet.

Track lifecycle events after applying:

```bash
divapply track applied https://example.com/job
divapply track screening https://example.com/job --follow-up 2026-05-15 --notes "Recruiter screen"
divapply track interview https://example.com/job
divapply track offer https://example.com/job
divapply track rejection https://example.com/job
divapply followups
divapply analytics
```

Lifecycle data is append-only in `application_events`. The current state is mirrored to the jobs table for status/dashboard compatibility.

## Answer Bank

`~/.divapply/answers.yaml` stores reusable answers for employer form questions. It is local-only and ignored by git.

```bash
divapply answers add "How many years of Python experience do you have?" "2 years."
divapply answers list
divapply answers match "Years using Python?"
```

The apply agent receives the answer bank in its prompt and reuses close matches for differently worded questions. Answers must stay factual and supported by the profile/resume.

## Auto-Apply Safety

No real submissions are run unless you confirm them.

```bash
divapply apply --dry-run
divapply apply --gen --url https://example.com/job
divapply apply --mark-applied https://example.com/job
divapply apply --mark-failed https://example.com/job --fail-reason "manual review"
divapply apply --reset-failed
divapply apply --yes
```

Use `--dry-run` first on new sites. `--gen --url ...` writes a prompt for manual review. `--yes` confirms real browser submission mode.

## Offline Selfcheck

```bash
divapply selfcheck
```

Selfcheck verifies imports, Python version, JobSpy import, config paths, DB init, coursework count, and local directories. It does not call job boards, LLMs, browsers, apply agents, or external sites.

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
