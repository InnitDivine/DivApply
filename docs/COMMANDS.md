# DivApply command guide

Type `divapply` to show the home screen and its eight-command menu. It does not start searching, make AI calls, or generate documents. Use `divapply run` to start preparation; you do not need to remember individual pipeline stages.

| Command | Purpose |
| --- | --- |
| `divapply` | Show the home screen and available commands without starting work. |
| `divapply run` | Search and finish pending resume/cover-letter PDF packets; never submit. |
| `divapply add "URL"` | Read one posting, score it, and prepare both PDFs. |
| `divapply add --file jobs.txt` | Prepare a list of URLs without opening application forms. |
| `divapply status --details` | Explain ready, missing, blocked, and failed packets without AI calls. |
| `divapply dashboard` | Review jobs and open documents. |
| `divapply apply --assist --url "URL"` | Assisted form filling; you review and submit. |
| `divapply settings --help` | Profile/search editor, setup, logins, coursework, saved answers. |
| `divapply jobs --help` | Explain, repair, export, track, and inspect saved jobs. |
| `divapply system --help` | Offline checks, backups, cleanup, migration. |

## Run options

- `--saved`: no discovery; finish the current queue.
- `--limit 3`: prepare at most three jobs, keeping each job's grading and documents together. Search results may exceed this number. Omit the limit (or use `0`) to finish all pending jobs.
- `--min-score 5`: generate documents at 5 or higher. The default is 7. Mandatory qualification, source, closed-posting, and market gates still apply.
- `--refresh`: reread and regrade saved jobs; keep existing documents, including your edits. Without it, current grades and ready packets are reused.
- `--dry-run`: preview without job-page requests, AI calls, or document generation. A fresh search cannot be predicted; use `--saved` to preview the exact saved selection.
- `--workers 4`: discovery concurrency. Preparation stays sequential and checkpoints each document immediately.

New or obsolete grades are refreshed from the live posting before scoring. Current high-scoring jobs with missing files are repaired without unnecessarily repeating AI grading. Text fallbacks are converted to PDFs. Ready packets are not regenerated. Archived/applied/closed jobs are not reopened by the everyday run.

Grading now follows a board listing to its matching employer/ATS posting, reads linked qualifications, and records the source URL and fetch time. If the full posting cannot be read, it reports a source error instead of grading a cached board summary. `divapply jobs explain "URL"` exposes the requirement audit. Legacy `rescore` also refreshes employer evidence.

Both PDF files must exist before a packet is called ready. Generation failures and partial stage failures return an error exit code. Other blockers (below threshold, unverified employer source, eligibility gaps, schedule review, retry limits) appear in the result summary; they are not represented as generated documents.

Scoring/tailoring send private candidate evidence and job descriptions to the AI provider configured in your local `.env`. Standard runs can use the full pending queue and incur API charges; use `--limit` to bound preparation. `run`, `add`, and `status` never authorize application submission.

## Recovery and occasional tools

```powershell
divapply jobs repair --url "URL" --retry-failed
divapply jobs export --out jobs.csv
divapply jobs track applied "URL"
divapply jobs followups
divapply settings coursework import transcript.json
divapply settings coursework summary
divapply settings answers list
divapply settings credentials --username you@example.com
divapply settings browser-login --browser chrome --url https://www.myworkday.com/
divapply system backup
divapply system cleanup
```

Cleanup previews first; `--yes` is needed to delete candidates. Generated documents and your education/profile data are not cleanup candidates.

## Compatibility

Existing scripts can keep using `init`, `edit`, `credentials`, `browser-login`, `import-coursework`, `coursework-summary`, `answers`, `export jobs`, `track`, `followups`, `analytics`, `explain`, `audit`, `repair`, `backup`, `cleanup`, `migrate`, and `prune`. These reuse the grouped implementations and are hidden from the main menu. `doctor` and `selfcheck` both route to `system check`.

`add-url` retains its old save-only default; the simpler `add` prepares by default. `apply-links` retains its explicit assisted batch workflow; `add --file` always prepares only. `rescore`, `sync`, specific `run` stages, and streaming remain legacy/advanced interfaces. Stage/stream/prune mode cannot be mixed with the everyday `--saved`, `--limit`, or `--refresh` options. Nothing was published or migrated automatically.

## Local verification (September 5, 2026)

- Full regression suite: 869 passed, 2 skipped. Ruff passed; mypy checked 58 source files; local wheel built successfully.
- An isolated two-job test used fictional candidate data and fixed AI responses through the real scoring, validation, CLI, database, and PDF code. It produced four one-page PDFs with 100% source-token coverage; all four were visually inspected. Repeating the run produced no extra model calls or duplicate documents.
- Interruption tests confirm each finished resume/cover is committed before the next job. Tests also cover missing files, bounded job selection, exhausted retries, stale grades, no-submit defaults, and preparation failure exit codes.
- The installed Windows CMD launcher passed a saved-job dry run and the combined offline system check. Existing candidate documents and coursework were preserved.
- This is not a live-provider, live-scraper, or browser-submission certification. A private-profile AI test requires separate approval; no real applications were submitted during these checks.

## Employer-grading verification (September 7, 2026)

- 934 tests passed, 2 skipped; Ruff, mypy, and local wheel build passed.
- Five public employer posting checks succeeded, including linked CalHR classification and duty-statement evidence.
- The installed CMD command passed the home menu and `run --saved --limit 3 --dry-run` checks against the local source.
- The grading-policy update makes prior grades need rechecking. Existing jobs and edited documents remain intact; the default PDF-generation threshold is still 7.
- Cumberlands education now renders as in progress, expected December 2026. The hypothetical completed-bachelor scoring option does not change factual resume or application claims.
- New real-provider grading and document generation were not executed in this verification. They use your saved private profile/resume and API balance and require approval for the agent to run.
