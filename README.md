# DivApply

[![PyPI](https://img.shields.io/pypi/v/divapply.svg)](https://pypi.org/project/divapply/)
[![Python](https://img.shields.io/pypi/pyversions/divapply.svg)](https://pypi.org/project/divapply/)
[![CI](https://github.com/InnitDivine/DivApply/actions/workflows/ci.yml/badge.svg)](https://github.com/InnitDivine/DivApply/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/InnitDivine/DivApply.svg)](LICENSE)

DivApply is a local-first job application assistant. It discovers jobs, enriches postings, scores fit, tailors resumes, writes cover letters, exports PDFs, and can optionally assist with browser-based applications.

```text
discover -> enrich -> score -> tailor -> cover -> pdf -> apply
```

DivApply works from your profile, resume, search preferences, and optional coursework. It is designed to preserve facts—not invent employers, credentials, degrees, skills, dates, metrics, or experience.

## Highlights

- Configurable searches across job boards and direct employer sources.
- Full-posting enrichment and canonical application links.
- Hybrid keyword, local-similarity, and optional LLM scoring.
- Required-versus-preferred qualification handling.
- Factual, job-specific resumes and cover letters with fail-closed ATS text validation.
- Local dashboard, lifecycle tracking, analytics, and safe exports.
- Hidden coursework context without automatic transcript disclosure.
- Confirmation-gated browser assistance with dedicated worker profiles.

## Requirements

| Feature | Requirement |
| --- | --- |
| Core CLI | Python 3.11+ |
| Full JobSpy discovery | Python 3.12 recommended; maintained Windows setup uses 3.12.13 |
| Default browser and PDF workflows | Playwright Chromium; auto-apply can also target supported installed browsers |
| AI scoring and documents | Gemini, OpenAI, or a compatible local endpoint |
| Auto-apply | Node.js 20+ and Codex CLI or Claude Code |

Python 3.14 can remain installed for other work, but run DivApply from a Python 3.12 virtual environment while upstream JobSpy pins remain in place.

## Install

Use an isolated virtual environment. This keeps DivApply and its browser dependencies out of your system Python.

### Windows PowerShell

```powershell
$Venv = "$HOME\.venvs\divapply"
py -3.12 -m venv $Venv
& "$Venv\Scripts\Activate.ps1"

python -m pip install --upgrade pip
python -m pip install --upgrade "divapply[full]"

$JobSpyWheel = "https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9"
python -m pip install --no-deps $JobSpyWheel
python -m divapply.jobspy_runtime
python -m playwright install chromium

divapply init
divapply doctor
```

If `py -3.12` is unavailable, install Python 3.12 or use an existing 3.12 interpreter explicitly.

### macOS and Linux

```bash
python3.12 -m venv ~/.venvs/divapply
source ~/.venvs/divapply/bin/activate

python -m pip install --upgrade pip
python -m pip install --upgrade 'divapply[full]'

JOBSPY_WHEEL='https://files.pythonhosted.org/packages/d5/2b/18863fcd3c544a69d81e351381a50036a33c21b61cc1c6de2a8f25931237/python_jobspy-1.1.82-py3-none-any.whl#sha256=93d638b35ffd30a714253e065907f68c5bac624e3937a3ad2ba09f618a072ee9'
python -m pip install --no-deps "$JOBSPY_WHEEL"
python -m divapply.jobspy_runtime
python -m playwright install chromium

divapply init
divapply doctor
```

### Install choices

| Package | Includes |
| --- | --- |
| `divapply` | Core CLI |
| `divapply[coursework]` | Core CLI plus PDF coursework import |
| `divapply[jobspy-runtime]` | Secure JobSpy dependency floor, without JobSpy itself |
| `divapply[full]` | Coursework plus the secure JobSpy runtime dependencies |

#### Why JobSpy uses a separate command

`python-jobspy` 1.1.82 declares `markdownify<0.14.0`, while the patched dependency floor requires `markdownify>=0.14.1`. DivApply therefore installs the secure floor first, then the exact hash-verified JobSpy wheel with `--no-deps`.

Because those published metadata ranges cannot overlap, `pip check` may report an intentional Markdownify conflict. Do not downgrade Markdownify to silence it. Use these supported checks instead:

```powershell
python -m divapply.jobspy_runtime
divapply selfcheck
divapply doctor
```

## First Run

```powershell
divapply init
divapply edit
divapply selfcheck
divapply doctor
```

`divapply init` is an interactive setup wizard. `divapply edit` opens the normal local-only editor for your profile and searches.

User data lives under `~/.divapply`:

- `profile.json` — applicant facts, work history, education, verified skills, and reusable form answers.
- `resume.txt` / `resume.pdf` — master resume evidence.
- `searches.yaml` — target roles, markets, schedules, boards, tiers, and filters.
- `.env` — API keys and runtime settings.
- `credentials.yaml` — optional job-site login credentials.
- `divapply.db` — local jobs, coursework, and application history.

These files are private and ignored by Git. Keep candidate facts in `profile.json`; keep job-search strategy in `searches.yaml` so old preferences do not become resume claims.

For a destination market, `profile.json` may define `resume_locations` entries with `city`, `province_state`, `match_patterns`, `use_for_resume_header: true`, and an optional exact `availability_statement`. A matching job then uses that city and state in its résumé and cover-letter header only. Street, postal, and application-form addresses continue to come from `personal` or `application_addresses`; see `profile.example.json` for a fictional example.

## Core Workflow

Run the full non-submitting pipeline:

```powershell
divapply run
divapply status
divapply dashboard
divapply export jobs --out jobs.csv
```

Run selected stages or inspect one posting:

```powershell
divapply run discover enrich
divapply run score tailor cover pdf
divapply add-url JOB_URL
divapply add-url JOB_URL --prepare --min-score 5
divapply explain JOB_URL
divapply rescore
```

`divapply run` never submits applications. Submission is a separate, confirmation-gated `divapply apply` command.

## Search Configuration

Most users should configure searches through `divapply edit`. The underlying `searches.yaml` remains human-readable:

```yaml
defaults:
  results_per_site: 50
  hours_old: 168

locations:
  - label: local
    location: "Exampletown, UT"
    remote: false
  - label: remote
    location: "Remote"
    remote: true

queries:
  - query: "IT Support Specialist"
    tier: 1
    location_labels: [local, remote]
  - query: "Help Desk Technician"
    tier: 2
    location_labels: [local, remote]
  - query: "Health Information Technician"
    tier: 3
    location_labels: [local, remote]

boards:
  - indeed
  - linkedin
```

Tier 1 is the strongest target, tier 2 is an adjacent path, and tier 3 is a broader fallback. Titles belong in `queries`; places belong in `locations`; schedule, benefits, market, and application-mode policy should remain structured search configuration. A posting with an explicit schedule that conflicts with its market policy is kept for manual review but cannot generate application documents or enter auto-apply; an exact configured schedule exception still takes precedence.

Configured official GovernmentJobs/SchoolJobs, JobAps, and CalCareers sources use deterministic current-vacancy adapters. A row is marked open only when the current official board exposes an exact job/application entry; expired filing deadlines are excluded. Rediscovery may restore a legacy or source-closed row, but it never overrides a job you archived yourself or one excluded by search policy.

For `divapply add-url`, a visible inactive/expired notice or terminal HTTP 404/410 response closes and source-archives the row even when the retired page still exposes stale job metadata. Hidden inactive branches used by live single-page applications are ignored.

Trusted static sources in private `~/.divapply/config/sites.yaml` may also define `location_label` and `default_location`. The default fills only a blank scraped location so a source can resolve to the correct configured market without overwriting concrete posting data.

Legacy aliases still load, but `divapply selfcheck` reports migration guidance.

## Scoring and Resume Safety

DivApply blends required/preferred keyword evidence, local similarity, and optional LLM judgment. Required non-substitutable gaps—such as a mandatory license or clearance—can cap a score. Preferred credentials should not block an otherwise strong match.

Provider or transport failures remain retryable rather than becoming fake low scores. Inspect score evidence with:

```powershell
divapply explain JOB_URL
```

Treat `profile.json` and your master resume as factual sources. Imported structured education fields are canonical for their academic values, and coursework may provide additional academic context. Generated documents may rephrase or prioritize supported facts, but must not turn coursework, labs, projects, or in-progress education into paid experience or earned credentials.

Resume PDFs use a one-column layout and are checked after rendering for selectable text, source-token coverage, and standard section order. A PDF that fails those machine-readability checks is not saved or offered for upload.

Validation modes are available when generating documents:

```powershell
divapply run score tailor --validation strict
divapply run score tailor --validation normal
divapply run score tailor --validation lenient
```

## Coursework

Coursework can improve matching without exposing raw transcript text:

```powershell
divapply import-coursework path\to\transcript.json
divapply coursework-summary
```

Supported formats are JSON, CSV, text, and PDF when the coursework extra is installed. Raw transcript text stays local. Selected completed-course facts may be included in scoring or tailoring prompts sent to your configured LLM, but coursework is not automatically copied into a resume.

## Browser Login and Auto-Apply

Start with one dry-run job:

```powershell
divapply apply --dry-run --limit 1 --min-score 7
```

Optional usernames and passwords can be stored in the permission-protected local `credentials.yaml` file. This file is not an encrypted credential vault:

```powershell
divapply credentials --username you@example.com
```

Save cookies separately in DivApply's dedicated browser profile by signing in interactively:

```powershell
divapply browser-login --url https://www.myworkday.com/
```

Then run the smallest real batch:

```powershell
divapply apply --yes --limit 1 --workers 1 --min-score 7
```

`apply` defaults to score 7 independently of the threshold previously used to generate documents. If you reviewed and prepared lower-scoring jobs, pass that same threshold explicitly, such as `--min-score 5`. DivApply reports the selected score window before launch and exits before opening a browser when no queued job matches it. A finite `--limit` is global across all workers.

Safety boundaries:

- Real application runs require explicit confirmation.
- Worker profiles are blank and dedicated; DivApply never clones your personal Chrome profile.
- The apply agent receives an allowlisted browser surface, without host shell or arbitrary page-code execution. Codex approval-required browser actions use automatic review while the agent remains read-only.
- CAPTCHA, unsupported authentication, and email-only flows fail closed. Gmail automation is unavailable.
- `RESULT:APPLIED` requires matching submission-origin and visible-confirmation evidence, but remains model-reported; verify important submissions yourself.
- Do not automate SSNs, banking details, payments, ID uploads, or biometric verification.

If a site rejects Playwright's browser, set `DIVAPPLY_BROWSER=chrome` in `~/.divapply/.env`, then use the same browser for `browser-login` and `apply`.

The ChatGPT desktop app's `@Browser` and `@Chrome` controls are not available to Codex CLI. They are a useful supervised alternative for applications that need your existing Chrome session; DivApply's unattended CLI path instead reuses its dedicated signed-in worker profile.

## Backups, Cleanup, and Privacy

```powershell
divapply backup
divapply cleanup
divapply cleanup --yes
```

Backups include profile, resume, searches, database, local config, and generated documents. Logs and secrets are excluded unless you explicitly add `--include-logs` or `--include-secrets`.

`divapply cleanup` previews dashboard benchmark/performance files, `.bak` files, and non-PDF sidecars in generated-document folders. Add `--include-backups` only when you intentionally want matching `divapply-backup-*.zip` archives removed.

Apply logs use user-only permissions and expire after 30 days by default. See [Privacy](docs/PRIVACY.md) for data boundaries and Git hygiene.

## Common Commands

```powershell
divapply init
divapply add-url JOB_URL
divapply edit
divapply doctor
divapply selfcheck
divapply run
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
divapply migrate
divapply prune --dry-run
divapply sync --dry-run
```

Run `divapply --help` or `divapply COMMAND --help` for full options.

## Development

```powershell
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
.\install.ps1 -Dev
.\.venv\Scripts\Activate.ps1

python -m pytest -q
ruff check .
```

On macOS or Linux:

```bash
./install.sh --dev
source .venv/bin/activate

python -m pytest -q
ruff check .
```

## Documentation

- [Privacy and factuality](docs/PRIVACY.md)
- [Operations and recovery](docs/OPERATIONS.md)
- [Migration notes](docs/MIGRATION.md)
- [Security audit report](docs/AUDIT_REPORT.md)
- [Release notes](CHANGELOG.md)
- [Publishing](PUBLISHING.md)
- [Contributing](CONTRIBUTING.md)
- [AI assistance disclosure](docs/AI_ASSISTANCE.md)

## License

DivApply is licensed under [AGPL-3.0-only](LICENSE).
