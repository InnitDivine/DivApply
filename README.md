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
python -m pip install --no-deps python-jobspy==1.1.82
python -m playwright install chromium
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
python -m pip install --no-deps python-jobspy==1.1.82
python -m playwright install chromium
divapply init
divapply edit
divapply doctor
```

Install directly from GitHub before a PyPI release is available:

```powershell
python --version  # expected on the maintained Windows setup: Python 3.12.13
python -m pip install "divapply[full] @ git+https://github.com/InnitDivine/DivApply.git"
python -m pip install --no-deps python-jobspy==1.1.82
```

Use `divapply` without extras for the lightest install. Use `divapply[coursework]` for PDF transcript import, `divapply[jobspy-runtime]` for the secure JobSpy runtime dependency floor, or `divapply[full]` for both coursework and JobSpy runtime dependencies. Because the current `python-jobspy` package pins `markdownify<0.14.0`, which conflicts with the CVE-2025-46656 fix in `markdownify>=0.14.1`, install DivApply's secure dependency floor first, then install exact `python-jobspy==1.1.82` separately with `--no-deps`. If JobSpy is missing, run `python -m pip install "divapply[full]" && python -m pip install --no-deps python-jobspy==1.1.82`. Until upstream relaxes that pin, `pip check` may still report the stale `python-jobspy` metadata conflict even when `pip-audit` shows no vulnerable `markdownify` version installed.

On Windows, DivApply installs plain `divapply`/`divapply.cmd` launchers instead of relying on a generated `divapply.exe`, so managed PCs that block generated console-script executables can still run `divapply` directly from `cmd`.

`divapply[jobspy-upstream]` is declared only for compatibility checks against upstream `python-jobspy` metadata. It is not part of the recommended install path because it allows pip to install the vulnerable upstream `markdownify` range.

Auto-apply mode also needs Node.js 18+ and an agent CLI such as Codex or Claude Code. It uses `DIVAPPLY_BROWSER` when configured, otherwise it defaults to Playwright Chromium, which is installed by the quick-start command. Firefox is optional and only needed if you explicitly run `divapply apply --browser firefox`.

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
python -m pip install --no-deps python-jobspy==1.1.82
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

Keep `profile.json` factual: identity, work authorization, pay answers, work history, education, verified skills, references, and reusable application answers. Do not put preferred job titles, employers, locations, reject lists, or search strategy in the profile; put those in `searches.yaml` so scoring is driven by the current search instead of stale profile prose.

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

Auto-apply launches a dedicated Chromium browser session for each worker, navigates to application pages, fills supported form fields from your profile and resume facts, uploads generated documents when available, answers screening questions through the selected agent backend, and shows progress in the live terminal dashboard.

The apply agent is launched without host shell access and with an exact browser-tool allowlist. CAPTCHA solving fails closed with `RESULT:CAPTCHA`; DivApply never puts a CAPTCHA-service key or host-command recipe in the agent prompt. Gmail automation is unavailable because the former integration is archived and its latest dependency tree has known High-severity advisories. Email-only applications and email verification therefore fail closed with `RESULT:FAILED:email_required`.

Cost-safe defaults are intentionally conservative: real auto-apply runs default to one job and one worker, and higher limits, multiple workers, unlimited continuous polling, or unbounded runs require `--allow-expensive`. Start with `divapply apply --dry-run --limit 1`, then use `divapply apply --yes --limit 1` for the lowest-cost real run.

Saved job-site logins are local-only and belong in `~/.divapply/credentials.yaml`, not `profile.json` or Git:

```powershell
divapply credentials --username you@example.com
divapply credentials --site workdayjobs.com --username you@example.com
divapply credentials --show
```

Omit `--password` and DivApply prompts for it without echoing it. Use site-specific entries for employers that need a different login.

To avoid signing in repeatedly, open the same persistent browser profile used by auto-apply, sign in once, complete any two-factor challenge, then close the browser:

```powershell
divapply browser-login --url https://www.myworkday.com/
divapply browser-login --url https://imh.wd108.myworkdayjobs.com/IntermountainCareers
```

Future `divapply apply --workers 1` runs reuse the worker-0 profile cookies for the configured browser. Use the same `--browser` and `--worker` values for login and apply when overriding the configured browser.

DivApply creates blank, dedicated worker profiles; it never copies your personal Chrome profile or another worker's cookies. Chrome worker profiles created by older DivApply releases are intentionally refused because they may contain copied personal browser credentials. Preserve an old profile as a backup, create a fresh dedicated profile, and sign in intentionally:

```powershell
Move-Item "$HOME\.divapply\chrome-workers\worker-0" "$HOME\.divapply\chrome-workers\worker-0.legacy-backup"
divapply browser-login --browser chrome --worker 0 --url https://www.myworkday.com/
```

The apply agent cannot execute page JavaScript or arbitrary browser code. DivApply records `applied` only when the agent's final three nonempty lines provide a matching submission origin, visible confirmation evidence, and exact `RESULT:APPLIED`; this remains a conservative model-reported check, so verify important submissions with the employer.

If Google says "This browser or app may not be secure", use real Chrome for both login and apply:

```powershell
divapply browser-login --browser chrome --url https://www.myworkday.com/
divapply apply --browser chrome --backend codex --model gpt-5.4-mini --dry-run --limit 1 --workers 1
```

To make real Chrome the default saved-cookie browser, set `DIVAPPLY_BROWSER=chrome` in `~/.divapply/.env`. Then both `divapply browser-login` and `divapply apply` use the Chrome worker profile unless you explicitly pass a different `--browser`.

Auto-apply has a bounded 45-minute per-job timeout by default, plus a 5-minute no-output timeout. Multi-step ATS flows can take several minutes; for fail-fast testing, set a shorter timeout for that session:

```powershell
$env:DIVAPPLY_APPLY_TIMEOUT="900"
divapply apply --backend codex --model gpt-5.4-mini --dry-run --limit 1 --workers 1
```

## Search Config

`searches.yaml` controls what DivApply looks for.

Example:

```yaml
queries:
  - query: "student assistant"
    tier: 1
  - query: "front desk"
    tier: 2
  - query: "customer service"
    tier: 3
locations:
  - location: "Exampletown, UT"
    remote: false
  - location: "Remote"
    remote: true
country: "USA"
boards:
  - indeed
  - linkedin
defaults:
  results_per_site: 50
  hours_old: 168
```

Tier `1` should be your best, most specific searches. Tier `2` should be strong adjacent matches. Tier `3` should be broad fallback searches. Keep job titles in `queries`, places in `locations`, schedule intent in `require_part_time`, and boards in `boards`. DivApply derives normal location filtering from `locations`; manual filters such as `location.accept_patterns`, `reject_patterns`, `exclude_titles`, `excluded_keywords`, and customer-service-specific hour filters are optional escape hatches only when a board repeatedly returns results that need cleanup before scoring.

Older search configs still load, but `divapply selfcheck` warns on legacy aliases so you can migrate gradually:
`search_terms` -> `queries`, `job_boards` or `sites` -> `boards`, `nearby_locations` -> `locations`, `reject_locations` -> `location.reject_patterns`, `target_titles` -> `include_titles`, `avoid_titles` -> `exclude_titles`, and `avoid_keywords` -> `excluded_keywords`.

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

Provider and transport failures do not become valid low scores: affected jobs remain retryable. LLM requests use separate network timeouts, at most three attempts, finite retry delays, and a 10-minute default total caller budget; advanced overrides are documented in `docs/OPERATIONS.md` and `.env.example`.

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
- Treat Gmail MCP opt-in as account access: enable it only when email application/verification automation is required.
- CAPTCHA and unsupported authentication challenges stop the run instead of expanding agent permissions.
- Browser workers use dedicated profiles only; personal or legacy unmarked Chrome profiles are never launched automatically.

Privacy details: [docs/PRIVACY.md](docs/PRIVACY.md)

## Common Commands

```powershell
divapply init
divapply add-url JOB_URL
divapply edit
divapply doctor
divapply selfcheck
divapply run
divapply run -w 4
divapply credentials --username you@example.com
divapply browser-login --url https://www.myworkday.com/
divapply status
divapply track applied JOB_URL
divapply followups
divapply analytics
divapply dashboard
divapply explain JOB_URL
divapply rescore
divapply export jobs --out jobs.csv
divapply answers list
divapply backup
divapply cleanup
divapply apply --dry-run
divapply apply --yes
divapply migrate
divapply prune --dry-run
divapply sync --dry-run
```

`divapply dashboard` opens an interactive local dashboard. Applied jobs include an Archive button so you can hide submitted applications without deleting their history. Archiving also removes generated resume and cover-letter files for that job. Use `divapply dashboard --static` when you only want to write a standalone HTML file.

`divapply cleanup` previews stale local dashboard benchmark/perf HTML files and backup-style `.bak` files. Run `divapply cleanup --yes` to delete the previewed files, or add `--include-backups` when you also want old `divapply-backup-*.zip` archives removed from the local backups folder.

Apply logs use private user-only files and expire after 30 days by default; set `DIVAPPLY_LOG_RETENTION_DAYS=0` to retain them. Recovery backups exclude logs and credentials by default. Add `--include-logs` and/or `--include-secrets` only when explicitly needed.

## Development

```powershell
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
.\install.ps1 -Dev
python --version  # expected on the maintained Windows setup: Python 3.12.13
python -m pip install -e .
divapply --version
python -m divapply --version
python -m pytest -q
ruff check .
```

Release notes: [CHANGELOG.md](CHANGELOG.md)

Publishing notes: [PUBLISHING.md](PUBLISHING.md)

Operations notes: [docs/OPERATIONS.md](docs/OPERATIONS.md)

AI assistance disclosure: [docs/AI_ASSISTANCE.md](docs/AI_ASSISTANCE.md)

