# Qualification audits and packet repair

## What the score now means

The 1-10 qualification score compares documented candidate facts with the job's
minimum requirements and role-specific skills. It is not a measure of how many
keywords overlap. Keyword and text-similarity results remain diagnostics.

- A supported, unmet minimum qualification limits the score to 4.
- An unresolved minimum, missing evidence, unread qualification document, or
  unsupported citation limits the score to 6 and requires review.
- A score of 7-10 requires evidence supporting the audited minimum qualifications.
- Preferred qualifications are distinct from minimum requirements. Alternative
  education/experience pathways must be assessed together, including their actual
  numeric experience or unit requirements.
- Coursework and home projects can demonstrate skills; they do not become paid
  professional experience or completed degrees.
- A scoring-only degree projection is labeled hypothetical and cannot establish
  present-day eligibility. With `assume_completed_bachelors: true`, matching treats
  the candidate's actual bachelor's field as completed without a score penalty or
  six-point ceiling. Degree completion remains a separate readiness flag; resumes
  and application answers still use factual current education status. Experience,
  licenses, field restrictions and other requirements are not waived.

Source verification, benefits, schedule, and relocation are separate readiness
flags. Job boards are discovery sources, not grading evidence: scoring first reads
the employer/ATS posting. A board's outbound link must match the job; a unique
published California job-control number can resolve the exact state posting.
Missing links, mismatched vacancies, blocked pages, and empty templates produce
explicit errors, not a grade from a cached board summary. Reading an employer page
does not silently authorize applications or promote an unknown source to verified.

The evaluator receives the fetched posting and linked evidence up to 60,000
characters. Visible job text supplements abbreviated structured metadata. Long
county bulletins are no longer cut at 6,000 characters. Oversized input is marked
incomplete, not silently treated as fully assessed. Public JavaScript rendering is
used when the initial page cannot supply the description.

CalCareers class specifications, linked exam bulletins, and duty statements are
read from official state domains. The modern CalHR portal is an exact-code/name
fallback for broken legacy links. Series minimums retain the advertised level and
shared rules, including specifications using different heading levels. A duty
statement cannot substitute for a failed qualification specification. An exam
fallback must name the classification it replaces. Other employer-linked
qualification documents are restricted to that posting's origin.

Each audited requirement records its status, exact posting quote, candidate
evidence, and explanation. The dashboard exposes this evidence. Obvious explicit
credential/year requirements omitted by the evaluator produce a review flag.
This is a reviewable aid, not an employer eligibility determination; an accurate
quote alone cannot prove that the model interpreted it correctly.

Version `employer-requirements-v4` also separates trainable duties from actual
hiring prerequisites. Coverage checks exclude optional substitutions, conditional
licenses, upload/privacy instructions, incomplete line fragments, and nonacademic
phrases such as "degree of independence." An accidentally JSON-encoded quote array
is decoded, but every individual quote must still exist in the supplied evidence.
Missing hours cannot be assumed to establish full-time-equivalent experience.

The actual posting URL, fetch time, scoring source, input fingerprint, and linked
document statuses are retained for inspection. Old-policy grades appear as needing
regrading, not as current confidence. Refresh/provider failures clear the current
grade while preserving the job and existing documents.

## Commands

```bat
divapply audit
divapply audit --details
divapply repair --limit 3 --dry-run
divapply repair --limit 3 --min-score 7
```

`audit` is an offline status report. `repair` processes one selected job at a time:
refresh the exact posting, grade requirements, generate missing approved documents,
and recover PDF conversion. It never submits applications. Successful grading is
saved per job. Existing documents are retained, not overwritten.

```bat
divapply repair --url "https://employer.example/job/123" --limit 1
divapply repair --limit 3 --no-rescore --no-prepare
divapply repair --limit 3 --retry-failed
```

Use quoted plain URLs in CMD, not Markdown links. The second command only reads
public posting pages; it makes no AI calls. `--retry-failed` resets exhausted
document attempts for the selected jobs. A missing saved document path is flagged;
if you renamed an edited document, reconnect it before regenerating.

`--limit 0` selects all saved, unarchived, unapplied jobs. Test a small batch first:
scoring and document generation send candidate/job information to the configured
AI provider and may incur API charges. Lowering `--min-score` can include uncertain
matches, but confirmed unmet minimum qualifications are excluded from automation.

`add-url --prepare` remains available for new direct employer links. Legacy
`rescore` now rereads employer pages and linked requirements too. The ordinary
`run --saved` workflow completes pending grading and document work; use
`run --saved --limit 3 --refresh` for a bounded live recheck. The default document
threshold remains 7; scores are not raised merely to trigger document generation.
`jobs explain "URL"` shows posting provenance and the requirement-by-requirement audit.

## Document handling

New output filenames use `Job_Position-Company.pdf` and
`Job_Position-Company_CL.pdf`. A short URL-identity subfolder prevents collisions
between jobs with the same title. Existing saved paths remain supported.

The PDF retry stage handles both resumes and cover letters, validates conversion,
and updates database links. It converts only database-referenced, approved text
fallbacks, not rejected drafts found by scanning a folder. Generic cleanup no
longer deletes text fallbacks merely because they have a `.txt` extension.

The dashboard distinguishes missing files, waiting generation, retry exhaustion,
source-verification requirements, and stale grades. All active jobs, including
ungraded and low-scoring jobs, remain visible with the All jobs filter.

## Related open-source workflows reviewed

- [ApplyPilot scorer](https://raw.githubusercontent.com/Pickle-Pixel/ApplyPilot/main/src/applypilot/scoring/scorer.py)
  and [detail reader](https://raw.githubusercontent.com/Pickle-Pixel/ApplyPilot/main/src/applypilot/enrichment/detail.py):
  upstream uses a saved-description score prompt with a 6,000-character prefix,
  and returns early when structured metadata supplies a description. DivApply
  retains the discovery/enrichment/document pipeline but adds live-source reading,
  visible-text completeness checks, linked requirements, and quote-audited grading.
- [ApplyPilot pipeline](https://raw.githubusercontent.com/Pickle-Pixel/ApplyPilot/main/src/applypilot/pipeline.py):
  the original six stages include PDF conversion. DivApply's everyday run keeps
  each job's scoring and approved PDF packet together with per-job checkpoints
  and explicit errors. Upstream was inspected, not installed or executed.
- [Job Ops](https://github.com/DaKheera47/job-ops): an inspectable pipeline from
  job discovery through scoring, tailored documents, and application tracking.
- [JobMatchAI](https://github.com/wadekarg/JobMatchAI): per-URL analysis, explicit
  re-analysis, and visible match/gap explanations before application assistance.
- [JobSpy](https://github.com/speedyapply/JobSpy): multi-board discovery, which
  still requires downstream full-posting and eligibility verification.

The changes use these workflow ideas, not copied implementation code or features
that manufacture missing candidate qualifications. No new service dependency or
autonomous submission behavior was added.

## Local repair on September 5, 2026

- Preserved all 78 active jobs, one previously archived job, and 50 coursework rows.
- Reconnected six renamed PDFs to their three Sutter Health jobs; their bytes were
  unchanged. Their existing filenames and user edits were preserved.
- Saved and retired 78 grades from the earlier scoring policy. These jobs now
  await the new audit rather than displaying old 6-7 scores as current evidence.
- Archived 53 old development-cache and scratch folders, without deleting them.
- Full recovery backup, including the six PDFs:
  `C:\Users\Dearr\.divapply\backups\divapply-backup-20260906T001921Z.zip`.
- Previous scores:
  `C:\Users\Dearr\.divapply\backups\legacy-scores-20260905.json`.
- File-move manifest:
  `C:\Users\Dearr\.divapply\dev\archive-20260905\manifest.json`.

Three public live-page refreshes succeeded: Placer Eligibility Specialist Trainee,
Sacramento IT Business Systems Analyst III, and CalCareers Research Data Analyst II.
The linked RDA II exam bulletin supplied previously missing numeric requirements.
The live AI grading/document-generation test was blocked by the app's approval
check before any model request. It still needs explicit approval to send saved
candidate/resume and job information to OpenAI. No applications were submitted,
and nothing was pushed to GitHub.

Verification: 835 tests passed and two were skipped; Ruff and mypy passed, the
wheel built successfully, and the installed CMD launcher passed an offline audit
and bounded preview. SQLite integrity and foreign keys were clean. A local-only
Chrome test verified all 78 dashboard cards, six document links, and score-filter
round trips without JavaScript errors. All six existing PDFs were visually reviewed.

## Local verification on September 7, 2026

- Updated the Cumberlands bachelor forecast to December 2026 in the private profile,
  master resume, and academic database. Generated education text includes the month
  and remains in progress. TMCC remains conferred, UNR transferred, and Bridgerland
  in progress. The earned CompTIA A+ is retained. Course names in the master resume
  now agree with the saved completed/current coursework lists; no course completion
  dates were added. An outdated blanket state-IT restriction was replaced with
  assessment of the advertised qualification pathways and review of uncertain units.
- Local recovery backup: `C:\Users\Dearr\.divapply\backups\education-before-20260907`.
  All 152 jobs (151 active and one archived) and 50 coursework rows were preserved.
  Existing tailored documents were not overwritten. SQLite quick check passed.
- Five public postings returned complete descriptions: Placer Accounting Technician
  and IT Analyst I; CalCareers Customer Service Technician / IT Associate and Program
  Technician II; and Sutter Facilities Coordinator II. Linked duty statements,
  class specifications, and an exam bulletin were read where available. The full
  Sutter check found the posting active; an initial raw-response impression of an
  inactive page was not used to close or delete the job.
- The latest saved run supplied real examples of false coverage warnings. Replaying
  that detector locally against 109 saved audits reduced its warnings from 167 to 7.
  This is a diagnostic, not a fresh AI grade or proof of eligibility. The remaining
  evidence must still be compared with the actual qualification pathways.
- Final suite: 934 tests passed, 2 skipped; Ruff, mypy (58 source files), patch
  whitespace checks, and the local wheel build passed. Tests include real grading
  failure patterns, source identity, long descriptions, current/legacy score display,
  alternative qualifications, unrelated degree fields, full-time-equivalent evidence,
  quote-array formatting, and generated December 2026 education text.
- The installed CMD launcher points at the edited local source. The home menu and
  a three-job saved-queue preview succeeded. The preview reports 109 grades needing
  the updated audit and 42 postings needing a successful refresh; it does not claim
  those jobs are newly scored or their packets generated.
- No new live AI requests, real application submissions, or GitHub pushes were made
  for this verification. A new private-profile test through the configured OpenAI
  API still requires explicit approval. Public fetch tests and local fixtures do
  not establish live model calibration or external application-site reliability.
