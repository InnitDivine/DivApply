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

Use Python 3.12 for the smoothest setup.

Recommended CLI install with `pipx`:

```powershell
python -m pip install --user pipx
python -m pipx ensurepath
pipx install "divapply[full]"
pipx run --spec playwright playwright install chromium firefox
divapply init
divapply edit
divapply doctor
```

Virtualenv install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install "divapply[full]"
python -m playwright install chromium firefox
divapply init
divapply edit
divapply doctor
```

Install directly from GitHub before a PyPI release is available:

```powershell
python -m pip install "divapply[full] @ git+https://github.com/InnitDivine/DivApply.git"
```

Use `divapply` without extras for the lightest install. Use `divapply[coursework]` for PDF transcript import, `divapply[jobspy-runtime]` for JobSpy-backed board discovery, or `divapply[full]` for both.

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
```

## First Run

```powershell
divapply init
divapply edit
```

This creates your local app folder and setup files:

- `profile.json` - personal details, work history, preferences
- `resume.txt` - master resume facts
- `searches.yaml` - job searches and filters
- `.env` - API keys and runtime settings
- `divapply.db` - local jobs database

These files are private and ignored by git.

Use `divapply edit` as the normal setup screen after initialization. It opens a local-only browser editor for:

- Personal/contact details
- Target work type and hourly pay
- Preferred roles and skills
- Work history, education, certifications, references, projects, and real metrics
- Search locations, query tiers, job boards, and filters

The editor saves `profile.json` and `searches.yaml` for you, so most users do not need to hand-edit JSON or YAML.

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
divapply apply --dry-run
divapply apply --yes
divapply migrate
```

`divapply dashboard` opens an interactive local dashboard. Applied jobs include an Archive button so you can hide submitted applications without deleting their history. Use `divapply dashboard --static` when you only want to write a standalone HTML file.

## Development

```powershell
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
.\install.ps1 -Dev
python -m pytest -q
```

Release notes: [CHANGELOG.md](CHANGELOG.md)

Publishing notes: [PUBLISHING.md](PUBLISHING.md)

Operations notes: [docs/OPERATIONS.md](docs/OPERATIONS.md)

AI assistance disclosure: [docs/AI_ASSISTANCE.md](docs/AI_ASSISTANCE.md)
