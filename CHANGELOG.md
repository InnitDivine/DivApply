# Changelog

All notable changes to DivApply will be documented here.

## 0.5.17

- Bound application prompts to the current CLI authorization, exact target identity, and field-level academic-record provenance while keeping generated and dry-run prompts unable to submit.
- Made exact `apply --url` targets bypass discovery geography only, without weakening work-authorization, scam, security, or wrong-job checks.
- Separated auto-review infrastructure denials from missing-answer, unverifiable-identity, and stale-prefill review blockers so queues stop only for infrastructure and job-specific blockers remain auditable without consuming attempts.
- Replaced blind GovernmentJobs saved-account trust and generic screening defaults with bounded work/education verification and exact profile or answer-bank evidence.
- Preserved semantic job URL queries and fragments while removing only known tracking parameters, preventing partial or recycled URLs from selecting the wrong posting.

## 0.5.16

- Restored Sutter Health application forms by allowing only source-scoped HTTPS Phenom API requests while continuing to block unrelated cross-origin requests and cross-site document navigation.
- Removed Chrome's unnecessary fake-media command-line flags and warning banner while retaining browser-level permission and notification denial.

## 0.5.15

- Routed approval-required Codex Playwright actions through supported automatic review while retaining the read-only sandbox, disabled shell/web tools, locked browser allowlist, and per-job navigation guard.
- Treated browser-navigation control cancellation as an infrastructure failure so it releases the job and stops the queue without consuming an application attempt.
- Documented why Codex CLI uses a dedicated persistent browser profile and cannot invoke the ChatGPT desktop app's Browser or Chrome controls.

## 0.5.14

- Updated Codex auto-apply startup to use the supported approval-policy configuration while retaining the read-only sandbox and disabled shell/web tools.
- Made backend exits and pre-agent preparation failures stop the queue as infrastructure failures without consuming job attempts or application events, with private diagnostics retained.
- Made finite application limits global across workers, counted skips and interrupts against the limit, and prevented a zero worker quota from becoming continuous polling.
- Added score-window preflight diagnostics and launch-banner visibility, with blocked/manual/unsafe/exhausted/shared-artifact parity; finite empty queues exit before browser startup while explicit continuous mode can wait for future work.

## 0.5.13

- Demoted explicit market schedule conflicts to manual review before document generation or application, while preserving exact configured exceptions and temporary full-time opportunities.
- Normalized Unicode dashes in exact target titles at the cover-letter generation boundary so valid official titles pass the ASCII document gate.
- Added trusted static-source location defaults that fill blank scraped locations without overwriting concrete posting data.
- Made visible inactive notices and terminal HTTP 404/410 responses outrank stale job metadata when refreshing a pasted URL, closing and archiving the row before document preparation.

## 0.5.12

- Added exact market-specific résumé availability statements without changing legal application addresses or search policy.
- Removed conflicting schedule language from tailored summaries and kept unmatched documents free of injected availability claims.

## 0.5.11

- Credited the highest completed degree and accepted experience substitutions without inventing mandatory paid IT tenure.
- Unified bounded work-history evidence across scoring, tailoring, judging, and validation while blocking unsupported help-desk and ticket claims.
- Improved requirement extraction for Sutter-style and public-sector postings, including exact phrase and token-boundary matching.
- Added content-neutral dense one-page résumé rendering with the existing selectable-text and source-coverage gates.
- Added document-only destination-market city/state headers without changing legal application addresses.
- Extended release privacy scans to configured résumé cities and bounded location-pattern matching.

## 0.5.10

- Rendered explicitly structured completed and current coursework in tailored résumé education sections.
- Kept active education programs labeled in progress when an expected graduation year is supplied.

## 0.5.9

- Reopened source-closed jobs when a configured official manual URL is verified live and open.
- Improved sparse one-page résumé readability with content-neutral adaptive typography and spacing.
- Hardened résumé and cover generation against unsupported posting-only skills, patient-facing, confidentiality, service-desk, help-desk, and ticket claims.
- Added an auditable deterministic safeguard for narrow judge verdicts that contradict exact candidate or canonical education evidence.

## 0.5.8

- Preserved Experience, Training, Education, and License requirement bodies in bounded scoring context instead of retaining only linked qualification preambles.

## 0.5.7

- Decoded entity-escaped HTML from structured job descriptions before persistence and scoring, preserving readable minimum qualifications while removing markup.

## 0.5.6

- Fixed GovernmentJobs agency boards that render a temporary zero before asynchronously loading current vacancies from the official agency endpoint.
- Added support for the current agency-card layout, same-origin fragment validation, duplicate-card removal, and structured employment/salary extraction.

## 0.5.5

- Added deterministic current-vacancy discovery for GovernmentJobs/SchoolJobs, JobAps, and bounded CalCareers searches, including official application links and filing-deadline checks.
- Added typed availability and archive provenance so verified-open legacy/source-closed jobs can return while user- and policy-archived jobs remain hidden.
- Made discovery policy resolve from each result's actual market, isolated current-market part-time fallbacks from destination-market career searches, and changed title allowlists to whole-term matching.
- Removed candidate-specific relevance scoring from enrichment and added deterministic GovernmentJobs and CalCareers detail extraction so current roles reach scoring without an LLM parser.
- Made long exact cover-letter titles deterministic and disambiguated academic seasons such as `Spring 2026` from similarly named software frameworks.

## 0.5.4

- Added deterministic Phenom employer-site discovery and current-state refresh so reused, open requisitions do not remain falsely expired.
- Made configured official job URLs immediately verifiable and eligible for targeted `add-url --prepare` scoring and document generation.
- Rebuilt resume PDFs as one-column ATS documents with selectable-text, token-coverage, and section-order gates that fail closed before persistence.
- Tightened resume and cover-letter evidence boundaries for early-career candidates, including paid-work/lab separation, exact target titles, and three-paragraph cover structure.
- Normalized scalar and array schema.org employment types into canonical schedule values.

## 0.5.3

- Prevented public-sector salary, position, application, résumé, transcript, and questionnaire text from becoming false required-skill gaps while preserving real requirement sections.

## 0.5.2

- Made `divapply edit` preserve scoped query labels, location labels, full/part-time schedule semantics, and the runtime-authoritative skill representation.
- Preserved every résumé header contact line so phone, email, LinkedIn, GitHub, and portfolio details survive PDF generation.
- Prevented prose compensation policies from being formatted or submitted as dollar amounts; mandatory unsupported numbers now require human review.
- Separated complete transcript storage from career-scoring context with completed-credit, relevance, and explicit coursework/skill filters.
- Made public pip install examples upgrade-safe so existing installations do not silently remain on an older DivApply release.
- Added typed per-market schedule, benefits, query-scope, and application-mode policy; discovery-only markets cannot auto-submit and unknown concrete locations require review.
- Hardened remote-location classification so board tags cannot override concrete out-of-market locations without posting evidence.
- Removed application/EEO/self-identification boilerplate from all LLM job context and calibrated equivalent-experience, keyword-heading, and degree-field reasoning.
- Added compact Additional Experience résumé rendering without corrupting job chronology or one-page layouts.
- Added a fail-closed distribution gate for archive paths, member types, size budgets, version binding, nested archives, and private-value collisions; release evidence revalidates package bytes and includes the exact manual JobSpy runtime in its SBOM.

## 0.5.1

- Removed the compatibility-only `jobspy-upstream` extra so no published DivApply dependency path can resolve JobSpy's vulnerable `markdownify<0.14.1` requirement.
- Kept the supported JobSpy setup on the audited `divapply[full]` dependency floor plus the exact hash-verified JobSpy 1.1.82 wheel.
- Added a regression that rejects vulnerable Markdownify versions anywhere in the universal lockfile.
- Mirrored every compatible upstream JobSpy dependency bound, added an installed-runtime validator/audit, and removed all retired-extra lock markers.

## 0.5.0

- Rebuilt the public repository from a privacy-clean root and retired prior candidate-specific distribution history.
- Added strict private-data boundaries, fictional public fixtures, and release privacy regression checks.
- Hardened scoring, tailoring, cover-letter evidence, application isolation, retries, backups, and supply-chain validation.
- Clarified the pip-first install path, JobSpy dependency tradeoff, and release smoke tests.
- Added packaging regression coverage for CLI entrypoint parity, README command alignment, and the secure JobSpy runtime contract.
- Updated CI and Docker smoke installs to exercise clean wheel installs plus the documented JobSpy no-deps step.
- Restored credential-free PyPI publishing and GitHub release promotion from a verified clean-root tag.

## 0.4.8

- Documented the required `python-jobspy` no-deps install step for pip-based setup and release smoke tests.
- Kept shipped search examples focused on role/title queries while locations and part-time constraints stay in separate fields.
- Switched default auto-apply browser setup from Firefox to Playwright Chromium.
- Simplified default search configuration to use accept-location filtering without default reject patterns.
- Made configured `locations` the default source for discovery location filtering, so normal configs do not need `accept_patterns`.
- Removed default title exclusion filters from shipped search config and made optional title excludes use safer term matching.
- Removed default excluded keyword filters from shipped search config so scoring and pruning decide fit by default.
- Stopped the editor and shipped defaults from emitting customer-service-specific schedule filters and duplicate search aliases.
- Added cleanup support for stale local dashboard benchmark files and backup archives.
- Added employer-specific relocation searches so selected Workday employers can bypass the normal location filter.
- Removed bundled applicant-specific coursework seed data from fresh installs.
- Kept profile search policy separate from applicant facts so scoring follows the active search config.

## 0.4.7

- Fixed interactive dashboard description loading after the lazy-rendering optimization.
- Preserved dashboard performance improvements while keeping static dashboards read-only.

## 0.4.6

- Removed the legacy one-off targeted resume command and module.
- Kept resume generation focused on the main `run tailor cover pdf` pipeline.

## 0.4.5

- Fixed fresh-install database startup by creating the database parent directory before opening SQLite.
- Added regression coverage for clean-home database initialization, matching GitHub Actions behavior.

## 0.4.4

- Added `divapply edit` as the local browser setup editor for profile and search configuration.
- Simplified profile/search examples around no-password profile data and tiered search queries.
- Preserved rich profile fields when saving through the editor, including references, certifications, and education metadata.
- Improved scoring/search setup compatibility for simple `skills`, preferred roles, and ApplyPilot-style search YAML.
- Added dashboard/accessibility, discovery, enrichment, Workday, SmartExtract, scoring, and editor regression coverage.
- Cleaned root documentation by moving migration and AI disclosure notes under `docs/`.

## 0.4.3

- Fixed neutral job scoring edge cases for preferred qualifications and hard requirement gaps.
- Kept company and source/job-board fields separate in scoring, apply prompts, logs, traces, and exports.
- Fixed one-off targeted resume job selection to prioritize highest fit scores before recency.
- Hardened resume and cover letter HTML escaping for generated PDFs.
- Added regression coverage for scoring, apply prompt context, PDF template output, and safe exports.

## 0.4.2

- Added a PyPI trusted-publishing workflow for `pip install divapply` releases.
- Reworked the README around the simple pip-first install path.
- Kept the GitHub clone installers as fallback/development options.

## 0.4.1

- Fixed the GitHub Actions PyPI publish workflow so it requests repository contents access before checkout.
- Kept the DivApply release/docs branding aligned with the Codex-assisted development disclosure.

## 0.4.0

- Renamed the project from ApplyPilot to DivApply.
- Moved the Python package to `src/divapply/`.
- Kept the public CLI entry point as `divapply`.
- Added a Windows bootstrap install flow for fresh GitHub clones.
- Added legacy migration support for previous `~/.applypilot` data.
- Added hidden coursework storage for profile matching.
- Added one-page resume shaping and tighter PDF layout defaults.
