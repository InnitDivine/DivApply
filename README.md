# DivApply

DivApply is a local-first job application assistant. It can find jobs, enrich postings, score fit, tailor resumes, write cover letters, export PDFs, and optionally help with browser-based applications.

It is designed to stay factual: it works from your profile, resume, saved preferences, and optional coursework notes. It should not invent jobs, credentials, degrees, tools, dates, metrics, or experience.

## What It Does

```text
discover -> enrich -> score -> tailor -> cover -> pdf -> apply
```

- Finds jobs from configured searches and direct sources.
- Expands postings with full descriptions and application links.
- Scores jobs against your real experience and required criteria.
- Separates required qualifications from preferred/nice-to-have items.
- Generates one-page tailored resumes and cover letters.
- Exports safe job tracking data.
- Can run browser apply flows only when you confirm it.

## Quick Start

Use Python 3.12 for the smoothest setup. The maintained Windows setup for this project currently uses Python 3.12.13. Python 3.14 may be installed on the same PC, but JobSpy-backed discovery is still expected to run from the Python 3.12 environment because of upstream dependency pins.

Recommended CLI install with `pip`:

```powershell
python --version  # expected on the maintained Windows setup: Python 3.12.13
python -m pip install --upgrade pip
python -m pip install "divapply[full]"
python -m pip install --no-deps python-jobspy
python -m playwright install chromium firefox
divapply init
divapply edit
divapply doctor
```

Virtualenv install, if you want the dependencies isolated:

```powershell
python --version  # expected on the maintained Windows setup: Python 3.12.13
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install "divapply[full]"
python -m pip install --no-deps python-jobspy
python -m playwright install chromium firefox
divapply init
divapply edit
divapply doctor
```

Install directly from GitHub before a PyPI release is available:

```powershell
python --version  # expected on the maintained Windows setup: Python 3.12.13
python -m pip install "divapply[full] @ git+https://github.com/InnitDivine/DivApply.git"
python -m pip install --no-deps python-jobspy
```

Use `divapply` without extras for the lightest install. Use `divapply[coursework]` for PDF transcript import, `divapply[jobspy-runtime]` for JobSpy runtime dependencies, or `divapply[full]` for both coursework and JobSpy runtime dependencies. Because the current `python-jobspy` package pins a vulnerable `markdownify` range, install DivApply's secure dependency floor first, then install `python-jobspy` separately with `--no-deps`. If JobSpy is missing, run `python -m pip install "divapply[full]" && python -m pip install --no-deps python-jobspy`. Until upstream relaxes that pin, `pip check` may still report the stale `python-jobspy` metadata conflict even when `pip-audit` shows no vulnerable `markdownify` version installed.

Auto-apply mode also needs Node.js 18+ and an agent CLI such as Codex or Claude Code.

## Clone Setup

Use this if you want the repo files locally.

```powershell
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
.\install.ps1
```

Update an existing clone:

```powershell
git pull
python -m pip install --upgrade -e ".[full]"
python -m pip install --no-deps python-jobspy
```

## First Run

```powershell
divapply init
divapply edit
```

This creates your local app folder and setup files:

- `profile.json` - applicant facts such as personal details, compensation, work history, education, and verified skills
- `resume.txt` - master resume facts
- `searches.yaml` - job searches and filters
- `.env` - API keys and runtime settings
- `divapply.db` - local jobs database

These files are private and ignored by git.

Use `divapply edit` as the normal setup screen after initialization. It opens a local-only browser editor for:

- Personal/contact details
- Compensation and verified skills
- Work history, education, certifications, references, projects, and real metrics
- Search roles, schedule/work-type filters, locations, query tiers, job boards, and filters

The editor saves applicant facts to `profile.json` and job-search intent to `searches.yaml`, so most users do not need to hand-edit JSON or YAML.

## Daily Workflow

```powershell
divapply doctor
divapply run
divapply status
divapply export jobs --out jobs.csv
```

Useful targeted runs:

```powershell
divapply run discover enrich
divapply run score tailor cover
divapply explain https://example.com/job
```

Use dry runs before any real browser submission:

```powershell
divapply apply --dry-run
divapply apply --gen --url https://example.com/job
divapply apply --yes
```

## Search Config

`searches.yaml` controls what DivApply looks for.

Example:

```yaml
queries:
  - query: "student assistant"
    tier: 1
  - query: "front desk part time"
    tier: 2
  - query: "customer service"
    tier: 3
locations:
  - location: "Logan, UT"
    remote: false
  - location: "Remote"
    remote: true
location:
  accept_patterns:
    - "Logan"
    - "Cache Valley"
    - "Remote"
  reject_patterns:
    - "Salt Lake City"
country: "USA"
boards:
  - indeed
  - linkedin
defaults:
  results_per_site: 50
  hours_old: 168
exclude_titles:
  - "senior"
  - "director"
  - "clearance required"
```

Tier `1` should be your best, most specific searches. Tier `2` should be strong adjacent matches. Tier `3` should be broad fallback searches.

## Resume Rules

Treat `resume.txt` as the source of truth.

- Keep it broad, truthful, and complete.
- Add only real work, projects, education, certifications, tools, and dates.
- Generated resumes are job-specific views of the master resume.
- Coursework can help matching, but it is not copied into resumes unless it belongs there.

Validation modes:

```powershell
divapply run score tailor --validation strict
divapply run score tailor --validation normal
divapply run score tailor --validation lenient
```

## Scoring

DivApply blends:

- Required/preferred keyword matching
- Local similarity scoring
- LLM judgment

Required gaps matter more than preferred gaps. Missing preferred certifications should not block a good job match. Missing required non-substitutable items, such as a required license, degree, or clearance, can cap the score.

Inspect a job:

```powershell
divapply explain https://example.com/job
```

## Exports

```powershell
divapply export jobs --out jobs.csv
divapply export jobs --out jobs.json --format json
```

Exports include safe fields such as title, company, source site, URLs, fit score, lifecycle dates, and redacted apply errors. They do not print your full profile, resume, transcript text, or secrets.

## Answer Bank

Save reusable factual answers for application forms:

```powershell
divapply answers add "How many years of Python experience do you have?" "2 years."
divapply answers list
divapply answers match "Years using Python?"
```

Answers are local-only and must stay supported by your profile or resume.

## Coursework

Optional coursework data can improve matching without exposing transcript text.

```powershell
divapply import-coursework path\to\transcript.json
divapply coursework-summary
```

Supported formats: JSON, CSV, text, and PDF if `pypdf` is installed.

## Safety

- Real auto-apply requires confirmation.
- Use `--dry-run` first on new sites.
- Do not upload private files to git.
- Review generated resumes before sending them.
- Do not let the browser agent enter SSNs, bank info, payment details, ID uploads, or biometric verification.

Privacy details: [docs/PRIVACY.md](docs/PRIVACY.md)

## Common Commands

```powershell
divapply init
divapply edit
divapply doctor
divapply selfcheck
divapply run
divapply run -w 4
divapply status
divapply dashboard
divapply explain JOB_URL
divapply export jobs --out jobs.csv
divapply backup
divapply cleanup
divapply apply --dry-run
divapply apply --yes
divapply migrate
```

`divapply dashboard` opens an interactive local dashboard. Applied jobs include an Archive button so you can hide submitted applications without deleting their history. Archiving also removes generated resume and cover-letter files for that job. Use `divapply dashboard --static` when you only want to write a standalone HTML file.

`divapply cleanup` previews stale local dashboard benchmark/perf HTML files and backup-style `.bak` files. Run `divapply cleanup --yes` to delete the previewed files, or add `--include-backups` when you also want old `divapply-backup-*.zip` archives removed from the local backups folder.

## Development

```powershell
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
.\install.ps1 -Dev
python --version  # expected on the maintained Windows setup: Python 3.12.13
python -m pytest -q
```

Release notes: [CHANGELOG.md](CHANGELOG.md)

Publishing notes: [PUBLISHING.md](PUBLISHING.md)

Operations notes: [docs/OPERATIONS.md](docs/OPERATIONS.md)

AI assistance disclosure: [docs/AI_ASSISTANCE.md](docs/AI_ASSISTANCE.md)

