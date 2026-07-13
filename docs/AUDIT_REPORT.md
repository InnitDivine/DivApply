# DivApply Engineering Audit

Audit date: 2026-07-13

## Outcome

The current tree has no open Critical code or current-tree privacy finding. The end-to-end career pipeline now fails closed at strict document gates, uses canonical transcript facts, keeps private runtime data outside Git, and has parity between pending-work counts and worker eligibility.

GitHub `main` was replaced with a validated single-root `0.5.0` baseline and published through a credential-free Trusted Publishing workflow. The `0.5.1` source line removes the remaining compatibility-only dependency path that could resolve vulnerable Markdownify metadata. Mutable legacy branches, tags, releases, Actions artifacts, deployments, and caches were removed or regenerated from the clean root. PyPI releases `0.4.2` through `0.4.8` were permanently deleted. GitHub Support ticket `#4557836` remains open to dereference closed pull-request refs `#2` through `#6`, garbage-collect the old objects, and clear cached views; the privacy incident remains open until GitHub Support confirms its server-side purge.

## Findings and remediation

### Critical

- Applicant/reference data and rendered application artifacts could enter the public tree and legacy distributions. Fixtures are anonymized, runtime paths are ignored, CI rejects recognized private artifacts, distribution preflight scans private identity/location/employment/education values, and GitHub now has a clean single-root baseline. Retired PyPI distributions are deleted; GitHub-managed closed-PR refs remain an external incident-response action under ticket `#4557836`.
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
- Launcher tests inherited a populated user database, hiding a missing-schema failure in pristine CI. DB-backed orchestration tests now inject initialized temporary databases, and the artifact-collision integration test exercises the real fail-closed guard.

### Low

- The compatibility-only `jobspy-upstream` extra could resolve `markdownify<0.14.1` even though supported installs already used the secure dependency floor. The unsafe extra and every stale lock marker are removed; the universal lock contains only patched Markdownify; all JobSpy installation surfaces use one hash-verified wheel; and installed-runtime validation enforces every other upstream bound.
- Known model grammar fragments, communication-channel overclaims, context relabeling, and PDF separator mojibake now have deterministic normalization or validation regressions.
- Superseded private documents are moved to dated backups so only current packets remain in active artifact directories.
- The retention test assumed POSIX no-follow symlink timestamp support. Its optional symlink fixture now degrades safely on Windows without suppressing the portable cleanup assertions.

## Verification

- Tests: 459 passed, 2 skipped; 58% branch coverage.
- Ruff: clean.
- mypy: clean for Linux and Windows targets.
- Offline selfcheck: all checks passed.
- Dependency audits: Python has no known vulnerabilities; npm reports 0 vulnerabilities.
- Supported JobSpy smoke: exact wheel 1.1.82 with pandas 2.3.3, regex 2024.11.6, and patched Markdownify 1.2.3 passes runtime-bound validation and installed-environment audit.
- Lockfile: valid and resolved.
- Release evidence: wheel and sdist pass Twine validation; SBOM and SHA256 evidence regenerate and verify.
- Privacy preflight: tracked tree, wheel, and sdist contain zero exact collisions with private identity, location, employment, education, or employer values; diagnostics redact source values.
- SQLite: `integrity_check=ok`; free pages reduced from 9,523 to 0.
- Document QA: two-page master résumé plus three one-page tailored résumés and three one-page cover letters rendered and visually inspected.
- Docker: unavailable on the audit workstation; the GitHub CI container gate passes on the clean release line.

## Architecture recommendations

1. Keep database-owned stage policies as the sole queue eligibility interface; forced target and rescore operations should remain explicit modes.
2. Add a trusted browser-event submission attestation layer so application state does not depend solely on model-reported text.
3. Move browser egress enforcement to a dedicated proxy or network policy if unattended submission becomes a supported deployment mode.
4. Replace noisy description n-gram gaps with a structured requirements extractor shared by scoring, explanations, and document generation.
5. Add a first-class manual-review promotion workflow for strict judge disputes rather than weakening strict mode.

## Security recommendations

1. Keep retired PyPI versions `0.4.2` through `0.4.8` deleted; track GitHub Support ticket `#4557836` until closed PR refs `#2` through `#6` are removed, storage is garbage-collected, and cached views are cleared. Preserve the restricted evidence bundles until incident closure.
2. Keep private profile, résumé, search, answer, credential, transcript, database, logs, browser profiles, backups, and generated documents outside the repository.
3. Treat the Playwright origin guard as defense in depth; continue denying arbitrary code/evaluate tools and minimize applicant data included in agent prompts.
4. Require successful CI, Python/npm audits, SBOM generation, checksums, and attestations before any tag publication.
5. Preserve fail-closed ACL behavior and test Windows DACL handling on native Windows CI.
6. Keep JobSpy outside published extras until upstream removes its vulnerable Markdownify upper bound; continue the exact, hashed/no-deps installation contract and dependency audit.

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
7. Raise branch coverage selectively in social integrations, discovery extraction, and CLI orchestration; prioritize security boundaries and failure paths over raw percentage.
8. Reassess first-class JobSpy packaging when upstream publishes dependency metadata compatible with the secure Markdownify floor.
