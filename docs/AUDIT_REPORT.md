# DivApply Engineering Audit

Audit date: 2026-07-12

## Outcome

The current tree has no open Critical code or current-tree privacy finding. The end-to-end career pipeline now fails closed at strict document gates, uses canonical transcript facts, keeps private runtime data outside Git, and has parity between pending-work counts and worker eligibility.

Public release still requires an operator-controlled history-remediation decision for applicant/reference fixtures that existed in earlier commits and tags. That operation intentionally is not automated because it requires coordinated force updates and cache/tag handling.

## Findings and remediation

### Critical

- Applicant/reference data and rendered application artifacts could enter the public tree. Fixtures are anonymized, runtime paths are ignored, CI rejects recognized private artifacts, and the current-tree identity scan is clean. Historical cleanup remains an explicit operator action.
- Strict résumé and cover validation could promote exhausted or judge-rejected drafts. Strict mode now preserves private review evidence, leaves database artifact paths empty, and promotes only validated documents.

### High

- Browser navigation relied on prompt-only origin instructions. Each apply worker now owns a validated Playwright initialization guard and unsafe browser tools remain disabled. Playwright is still defense in depth, not a complete network sandbox.
- Archived jobs could re-enter active stages or race in-progress writes. Active predicates, archive refusal, guarded persistence, lifecycle analytics, and streaming termination are now consistent.
- Missing target priority, false remote board labels, and prefix-only descriptions inflated weak jobs. Priority caps fail closed, concrete locations require posting evidence, and bounded contexts preserve both head and tail.
- Editable education facts could override newer transcript data. Structured academic records now own GPA, earned-credit scope, program fields, and expected graduation data.
- Private file creation and migration could suppress ACL failures. Sensitive text writes are strict by default; copies use protected sibling promotion; database/config/artifact files receive explicit user-only permissions.
- Candidate geography, employers, and sites leaked into generic package behavior. Address and schedule exceptions now come from private profile/search configuration; shipped site/employer registries are generic.
- Tag releases omitted Python vulnerability auditing. Release verification now runs the locked Python audit in addition to the npm audit.

### Medium

- Queue count SQL duplicated worker predicates. A database-owned stage predicate now feeds both selection and counting for score, tailor, and cover.
- Generated documents used a fixed technical-skills presentation and printed ambiguous prior-school credits. Role-appropriate headings are allowlisted; credits render only for an active program with total-earned scope.
- The master résumé PDF parser treated wrapped bullets as new entries and misclassified the home-lab heading. Indented continuations and heading aliases are now tested.
- Database free-page bloat accumulated after archival. The private database was backed up, integrity-checked, and compacted.

### Low

- Known model grammar fragments, communication-channel overclaims, context relabeling, and PDF separator mojibake now have deterministic normalization or validation regressions.
- Superseded private documents are moved to dated backups so only current packets remain in active artifact directories.

## Verification

- Tests: 451 passed, 2 skipped.
- Ruff: clean.
- mypy: clean for Linux and Windows targets.
- Offline selfcheck: all checks passed.
- Dependency audits: Python has no known vulnerabilities; npm reports 0 vulnerabilities.
- Lockfile: valid and resolved.
- SQLite: `integrity_check=ok`; free pages reduced from 9,523 to 0.
- Document QA: two-page master résumé plus three one-page tailored résumés and three one-page cover letters rendered and visually inspected.
- Docker: unavailable on the audit workstation; container build remains enforced by CI.

## Architecture recommendations

1. Keep database-owned stage policies as the sole queue eligibility interface; forced target and rescore operations should remain explicit modes.
2. Add a trusted browser-event submission attestation layer so application state does not depend solely on model-reported text.
3. Move browser egress enforcement to a dedicated proxy or network policy if unattended submission becomes a supported deployment mode.
4. Replace noisy description n-gram gaps with a structured requirements extractor shared by scoring, explanations, and document generation.
5. Add a first-class manual-review promotion workflow for strict judge disputes rather than weakening strict mode.

## Security recommendations

1. Coordinate history remediation for prior private fixture data, including affected tags, branch protection, forks/caches, and documented incident closure.
2. Keep private profile, résumé, search, answer, credential, transcript, database, logs, browser profiles, backups, and generated documents outside the repository.
3. Treat the Playwright origin guard as defense in depth; continue denying arbitrary code/evaluate tools and minimize applicant data included in agent prompts.
4. Require successful CI, Python/npm audits, SBOM generation, checksums, and attestations before any tag publication.
5. Preserve fail-closed ACL behavior and test Windows DACL handling on native Windows CI.

## Performance recommendations

1. Schedule explicit backup-plus-VACUUM maintenance after large archival/import cycles.
2. Benchmark the active/pending partial indexes with realistic database sizes before adding more full-description indexes.
3. Keep bounded head-and-tail job context; consider deterministic section extraction before increasing LLM context size.
4. Batch external discovery carefully and keep LLM scoring sequential/rate-aware unless provider limits and transaction behavior are measured.

## Technical debt roadmap

1. Trusted submit-event attestation and confirmation evidence.
2. Stronger browser/network isolation with redirect and DNS-rebinding resistance.
3. Structured requirement/gap extraction to replace noisy keyword fragments.
4. Explicit manual approval and artifact provenance UI for strict-review exceptions.
5. Target-family project selection based on structured project evidence rather than prompt preference alone.
6. Native container verification on developer workstations where Docker is available.
