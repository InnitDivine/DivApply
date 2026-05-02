# DivApply Privacy

DivApply is local-first. It reads private files from your machine and writes generated job-search artifacts under your local app directory. Do not commit those files.

## Private Files

- `.env`: API keys, model settings, browser/apply settings. Never commit.
- `profile.json`: personal details, work authorization, EEO choices, compensation, education, answers. Never commit.
- `answers.yaml`: reusable employer-question answers for auto-apply. Keep local and factual.
- `resume.txt` / `resume.pdf`: master resume. Never commit.
- `searches.yaml`: job targets, locations, blacklists, preferences. Treat as private.
- `divapply.db`: jobs, scoring metadata, application status, hidden coursework rows. Never commit.
- Coursework/transcripts: imported into SQLite for hidden matching knowledge. Do not commit source transcripts.
- Generated resumes: tailored output in `tailored_resumes/`. Review before sharing.
- Cover letters: generated output in `cover_letters/`. Review before sharing.
- Logs: apply and agent logs can include URLs, form labels, file paths, and snippets. Treat as private.
- Browser state: worker profiles, cookies, sessions, and MCP config files are local only.
- Screenshots: debug screenshots can show private application forms. Never commit.

## Safe Commands

- `divapply coursework-summary` prints only row count, schools, subject areas, inferred skills, and import sources.
- `divapply export jobs --out jobs.csv` exports safe tracking columns and redacts likely emails, phone numbers, and secrets from `apply_error`.
- `divapply selfcheck` runs offline and does not call job boards, LLMs, browsers, apply agents, or external sites.
- `divapply explain JOB_URL` prints score metadata only, not resume/profile/transcript text.
- `divapply followups` and `divapply analytics` print lifecycle metadata only.

## Factuality

DivApply should only rephrase and emphasize existing facts. It must not invent jobs, employers, credentials, licenses, degrees, skills, coursework, tools, dates, or metrics. Hidden coursework helps matching and reasoning; transcript text is not automatically copied into resumes.

## Git Hygiene

`.gitignore` blocks local/private/generated files such as `.divapply/`, `.applypilot/`, `.env`, `profile.json`, `resume.txt`, `answers.yaml`, `divapply.db`, generated resumes, cover letters, logs, browser state, and screenshots.

Examples in docs must be fake. Use placeholders like `Example College`, `Example Company`, and `https://example.com/job`.
