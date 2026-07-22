# DivApply critical-boundary remediation

## §G

- G1: eliminate Critical paths where untrusted job pages can drive host shell/files, inherit unrelated secrets, or cross-contaminate applicant artifacts.
- G2: keep automated applications functional inside least-privilege browser-only tooling; fail closed when CAPTCHA/email automation needs unavailable authority.
- G3: preserve baseline behavior outside named boundary changes; full configured test/lint/audit gates green.
- G4: bind every generated application artifact to one stable job identity; ⊥ wrong-job upload/delete.
- G5: preserve recoverability: transient provider failure remains retryable; backup captures active committed DB state.
- G6: bound network retry cost; make Windows/release/container paths reproducible + least privilege.
- G7: current market → part-time work incl IT/office/customer-service/hospitality/retail/warehouse; fast-food/quick-service excluded. Destination markets → well-paid benefited full-time IT/health-tech/public-sector/office pathways.

## §C

- C1: job pages + embedded instructions = hostile input.
- C2: automated + generated manual commands get no unrestricted shell, host sandbox bypass, web-search tool, or unsafe Playwright code runner.
- C3: agent env/prompt excludes unrelated credentials; CAPTCHA secret never enters prompt.
- C4: each worker owns staging dir; no shared mutable resume/letter path; transient artifacts removed after run.
- C5: Gmail MCP retired; legacy opt-in fails closed until audited maintained replacement exists.
- C6: first-run worker profile blank/dedicated; never auto-clone user's Chrome profile.
- C7: tests after each change; no Critical finding may remain open.
- C8: legacy generated paths preserved when unambiguous; shared path → apply reject + archive keeps shared file.
- C9: backup failure leaves prior target intact; output ≠ source/link/root; ⊥ raw copy of live SQLite/WAL DB.
- C10: provider/transport failure ≠ valid low score; retry bounded + observable.
- C11: Windows-first paths execute on Windows CI; privileged release jobs ⊥ run repository build/test code.
- C12: security tightening may reduce automation shortcuts; ⊥ broaden browser/network/file authority.
- C13: applicant facts/coursework/private search config stay local; ⊥ Git/release artifact.
- C14: paid experience ≠ lab/project/coursework; in-progress training ≠ earned cert/degree.
- C15: search priority + location scope explicit/configurable; absent new keys preserves old behavior.
- C16: current transcript rows all eligible for bounded scoring context; selection deterministic + recent/relevant-first.
- C17: résumé/tailor language may position target fit; ⊥ imply prior target-role employment or invent metrics.
- C18: current-market full-time + fast-food/quick-service ⊥ active; destination part-time/service-industry ⊥ active; destination office support allowed.
- C19: in-progress Public Health B.S. + IT training inform target fit; ⊥ earned/completed wording before conferral.

## §I

- I1: `gmail_mcp_enabled()` → `False`; truthy legacy `DIVAPPLY_ENABLE_GMAIL_MCP` rejected with audited-dependency diagnostic.
- I2: `build_prompt(..., upload_dir: Path|None, gmail_enabled: bool=False)` accepts an owned work dir below `APPLY_WORKER_DIR`, or creates a unique one when omitted; stages upload PDFs only below it; CAPTCHA/email text follows authority.
- I3: `_make_mcp_config(..., enable_gmail: bool=False)` always uses locked Playwright; `enable_gmail=True` rejected.
- I4: `_build_agent_command(...)` + `get_manual_command(...)` lock Claude to `dontAsk` + explicit MCP tools; lock Codex to read-only/no approvals + shell/web disabled; unsafe Playwright runners denied.
- I5: `_agent_environment(backend)` allowlists OS/runtime + selected backend-auth variables; drops application/third-party secrets.
- I6: `run_job` resets worker dir before staging; process cwd/prompt/MCP/uploads share worker ownership; finally removes worker transient dir.
- I7: `setup_worker_profile` creates dedicated blank profile + v2 ownership marker; refuses unmarked legacy profile; no host-profile discovery/copy.
- I8: `ensure_mcp_runtime(...)` → lock-digest cache below `APP_DIR`; secret-minimized public-registry frozen install; absolute Node/server paths; fail closed.
- I9: `job_artifact_stem(job)` → readable sanitized prefix + stable SHA-256 URL identity; same job stable, distinct URL distinct path.
- I10: `run_scoring(...)` → success count excludes retryable provider failures; failures retain `fit_score=NULL` + retry metadata.
- I11: `create_backup(...) -> BackupResult` preserved; archive DB member always consistent snapshot of `get_active_db_path()`.
- I12: `LLMRequestPolicy.from_env()` → typed connect/read/write/pool/attempt/total/delay limits.
- I13: `open_private_text(...)` → no-follow private create/append; Windows DACL failure → explicit failure for sensitive logs.
- I14: `parse_submission_proof(output, job)` → exact final `{SUBMISSION_ORIGIN,CONFIRMATION,RESULT:APPLIED}` or reject.
- I15: profile experience context → labeled `professional_*` vs `project_*`; legacy ambiguous years labeled unspecified, never paid.
- I16: search intent → validated `target_families[{name,priority}]` (policy, not applicant evidence); query `location_labels[]` scopes crawl by `location.label||location.location`; scorer sees priorities + all tier groups without silent first-20 loss.
- I17: coursework selector → per-school bounded union of academic-term-parsed newest + search-relevant courses; stable dedup/order; old rows remain stored.
- I18: tailor prompt → factual target positioning; metrics only when present; coursework/project facts cannot become paid duties.
- I19: local career-data migration → backup first; profile/resume/search/employer config factual + targeted; stale impossible-location jobs archived, not destroyed.
- I20: active pipeline query/stats boundary → `archived_at IS NULL`; archive stage/count remains separately visible.
- I21: scorer priority policy → P1 primary/P2 bridge eligible 7+; P3/outside + non-exempt part-time/per-diem/seasonal capped 6 when `preferred_schedule=full_time`.
- I22: JobSpy remote classifier → on-site contradiction rejects; concrete location + board tag needs explicit description remote evidence; broad/remote location accepted.
- I23: validation/orchestration → JSON validator accepts original résumé evidence; all-failed tailor/cover/PDF returns error, mixed returns partial.
- I24: transcript `schools` records overlay matching profile GPA/earned-credit facts at load time; editable profile facts cannot override newer canonical academic evidence.
- I25: one job-address selector feeds apply prompts + cover generation/PDF headers.
- I26: each apply worker owns a generated Playwright init-page route guard; active requests stay on validated job/application origins.
- I27: tailor presentation → model selects allowlisted technical/core skills heading; code owns current-program date/GPA/credit rendering.
- I28: public package consumes private address/employer/site selectors; no candidate geography/employer constants in generic scoring/config.
- I29: pending-work catalog → one DB-owned predicate builder feeds selection + count for score/tailor/cover; forced target/rescore remain explicit.
- I30: typed market resolver maps concrete `City, ST` to one location label; scorer/apply overlay that market's schedule, benefits, + application mode; unknown concrete city gets no guessed default.
- I31: private source registry → curated official employer/agency feeds by current/destination market; noisy disabled source absent from crawl targets.
- I32: `job_has_schedule_exception(search_config,job) -> bool`; `composite_score(...,schedule_exception=False)` + `score_job(...,application_mode="active")` accept only trusted structured policy.
- I33: structured score policy carries `preferred_schedule`, `require_part_time`, optional `max_hours_per_week`, `require_benefits`, + `application_mode`; posting-derived evidence cannot override config.
- I34: each discovered job persists `market_label`, `search_query`, `application_mode`, normalized schedule/hours, + `source_verification`; unresolved aggregators stay non-actionable.
- I35: release cleanup helper validates containment + every link/reparse boundary before recursive mutation.
- I36: configured official Phenom source → deterministic embedded-DDO search adapter; exact live `JobPosting` URL may enter official refresh path.
- I37: `validate_ats_pdf(source_text,pdf_path,required_sections) -> report`; missing/scrambled text layer → raise + delete output.
- I38: official discovery row → `availability_state`, `availability_checked_at`, `last_seen_at`; archive lifecycle → `archive_reason=user|policy|legacy|source_closed`.
- I39: official-government adapters → GovernmentJobs/SchoolJobs rendered listing parser; JobAps table parser; CalCareers bounded postback parser; no selector-cache/LLM trust decision.

## §R

- R1: OpenAI CLI: danger bypass intended only for externally isolated runners; sandbox/approval/config/MCP-tool controls available. https://developers.openai.com/codex/cli/reference https://developers.openai.com/codex/config-reference
- R2: Claude Code: bypass mode intended for containers/VMs; `dontAsk`, `--tools`, strict MCP config, allow/deny controls available. https://code.claude.com/docs/en/permission-modes https://code.claude.com/docs/en/cli-usage
- R3: Playwright MCP: v0.0.72 renamed code runner `_unsafe`; v0.0.76 added path traversal checks; v0.0.78 enables Chromium sandbox by default. https://github.com/microsoft/playwright-mcp/releases
- R4: uv: `uv.lock` universal across OS/arch/Python markers; `uv sync --locked` rejects stale metadata. https://docs.astral.sh/uv/concepts/projects/layout/ https://docs.astral.sh/uv/concepts/projects/sync/
- R5: GitHub Actions: full commit SHA = only immutable action reference. https://docs.github.com/en/actions/reference/security/secure-use
- R6: npm: `package-lock.json` records exact tree; `npm ci` requires matching lock, never rewrites it; `--ignore-scripts` blocks lifecycle scripts. https://docs.npmjs.com/cli/commands/npm-ci/ https://docs.npmjs.com/cli/v11/configuring-npm/package-lock-json/
- R7: Gmail MCP repo archived 2026-03-03; latest `1.1.11` dependency tree pulls obsolete MCP SDK + runtime `mcp-evals`; local `npm audit --omit=dev` → 4 High. https://github.com/GongRzhe/Gmail-MCP-Server https://www.npmjs.com/package/@gongrzhe/server-gmail-autoauth-mcp
- R8: Python `sqlite3.Connection.backup()` works while DB accessed concurrently; read-only URI mode avoids accidental source creation/write. https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup
- R9: HTTPX supports per-request + separate connect/read/write/pool timeouts; scalar timeout ≠ total retry deadline. https://www.python-httpx.org/advanced/timeouts/
- R10: Windows `icacls /inheritancelevel:r` removes inherited ACEs; `/grant:r *SID:F` replaces explicit grant for numeric SID. https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls
- R11: uv Docker guidance: pin image SHA for reproducibility; copy `uv.lock`; `uv sync --locked --no-editable`; activate project environment via `PATH`. https://docs.astral.sh/uv/guides/integration/docker/
- R12: GitHub recommends least-privilege workflow tokens; artifact attestations require scoped `id-token:write` + `attestations:write`. https://docs.github.com/en/actions/reference/security/secure-use https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- R13: `actions/attest@v4` replaces wrapper actions; provenance accepts checksum subjects; permissions require `id-token:write` + `attestations:write` + `artifact-metadata:write`; uv exports CycloneDX 1.5 from lock. https://github.com/actions/attest https://docs.astral.sh/uv/concepts/projects/export/
- R14: Bridgerland IT = hands-on hardware/software/OS/network/security/cloud deployment/support/troubleshooting; A+/Net+/Sec+ available, not implied earned. https://btech.edu/information-technology/
- R15: BLS support duties = diagnose/document issues, guide users, setup/repair/install/training; EHR app support is recognized specialization. https://www.bls.gov/ooh/computer-and-information-technology/computer-support-specialists.htm
- R16: health-info technologists support EHR/clinical data/privacy; 15% 2024–34; medical-records specialists 7%; entry requirements vary. https://www.bls.gov/ooh/healthcare/health-information-technologists-and-medical-registrars.htm https://www.bls.gov/ooh/healthcare/medical-records-and-health-information-technicians.htm
- R17: RHIT eligibility requires CAHIIM-accredited HIM associate-level academic requirements/reciprocity; public-health BS alone ≠ eligible. https://www.ahima.org/certification-careers/certifications-overview/rhit/
- R18: municipal IT Technician I class = entry level, little/no related work, hardware/software support + desktop/peripheral install/config; validates public-sector bridge. https://www.governmentjobs.com/careers/rosevilleca/classspecs/newprint/1512986
- R19: Playwright MCP `--init-page` can install context routes; built-in origin lists explicitly ≠ security boundary/redirect control. https://github.com/microsoft/playwright-mcp/blob/main/README.md
- R20: Attain official board lists remote part-time IT Support Specialist; valid current-market career-building lead @ 2026-07-13. https://job-boards.greenhouse.io/attainpartnershidden
- R21: iWorQ official careers = Cache Valley SaaS/public-sector software employer + health/dental/vision/life/retirement benefits. https://iworq.com/careers/
- R22: SDL official board lists current-market Information Systems/student technical roles; student work = paid career pathway. https://spacedynamicslaboratory.applytojob.com/ https://www.sdl.usu.edu/careers/internships/
- R23: destination official IT feeds expose Sacramento technology/system roles. https://careers.smud.org/go/Information-TechnologyTelecommunications/9107600/ https://careers.csus.edu/en-us/listing/
- R24: CPython 3.12 ZIP constructor reads the declared central directory into memory before exposing `infolist`; TAR PAX/GNU handlers read extension payloads before yielding the logical member. Raw EOCD/header budgets must precede stdlib construction. https://github.com/python/cpython/blob/v3.12.13/Lib/zipfile/__init__.py https://github.com/python/cpython/blob/v3.12.13/Lib/tarfile.py
- R25: `setup-uv` adds uv—not a synced project venv—to PATH by default; project tools run via `uv run` or explicit environment activation/path. https://github.com/astral-sh/setup-uv https://github.com/astral-sh/uv/blob/main/docs/guides/integration/github.md

## §V

- V1: ∀ automated/manual agent launch: no `bypassPermissions`/`--dangerously-bypass-approvals-and-sandbox`; built-in shell disabled; only declared MCP browser/email tools reachable.
- V2: ∀ agent child env: `CAPSOLVER_API_KEY`, `GITHUB_TOKEN`, login passwords, unrelated provider keys absent; required selected-backend auth may pass.
- V3: ∀ Playwright MCP configs: exact `@playwright/mcp@0.0.78`; browser sandbox + service-worker block requested; `browser_run_code` + `browser_run_code_unsafe` unavailable to both backends.
- V4: ∀ concurrent workers A≠B: process cwd + staged resume/letter/MCP/prompt paths disjoint, resolved beneath own worker dir; finally leaves no transient run artifacts.
- V5: ∀ CAPTCHA prompt: no resolver key/API/shell recipe; instruction terminates `RESULT:CAPTCHA`.
- V6: Gmail MCP absent from runtime/tool/prompt surface; truthy legacy opt-in fails closed until audited maintained replacement exists.
- V7: ∀ worker profile: marked v2 dedicated blank origin; no automatic copy/read of local Chrome profile; unmarked legacy profile cannot launch.
- V8: full `pytest`, configured Ruff, package dependency audit pass; security regression tests cover V1–V7.
- V9: ∀ manual URL redirects: each target validated before request, final URL validated, bounded hop count; private/local target never fetched.
- V10: reliability event commits iff recorder entered outside caller transaction; active caller transaction remains active + rollbackable.
- V11: direct/transitive dependency floors exclude known audited vulnerable versions; project + active environment audits pass.
- V12: Chrome lifecycle terminates only PIDs it launched/tracks; occupied CDP port fails closed without port-owner kill.
- V13: installer recreate target resolves to a non-root, non-link descendant of repository before recursive deletion.
- V14: ∀ CI/release → `uv==0.11.28` + `uv.lock` + `--locked`; external actions full SHA; branch coverage ≥50%; mypy Linux+Windows clean.
- V15: ∀ MCP runtime install → exact bundled packages + integrity lock + secret-minimized frozen `npm ci --ignore-scripts`; agent MCP configs use cached Node entry points; ⊥ `npx`.
- V16: bundled MCP runtime `npm audit --omit=dev --audit-level=high` passes; archived/vulnerable server packages unreachable.
- V17: score label without numeric value → score `0`; numeric value clamps to `1..10`.
- V18: ∀ new resume/cover artifacts A,B with distinct job URL → distinct stable stems; duplicate stored path → ⊥ apply; archive one row → ⊥ delete file referenced by another row.
- V19: provider/transport scoring exception → `fit_score`, `scored_at` stay NULL; error + attempt persist; retry attempts ≤5 with delay ≤24h; later success clears retry state.
- V20: ∀ backup with active DB → SQLite backup snapshot from `get_active_db_path()` + `integrity_check=ok`; ZIP staged + verified + atomic promote; legacy active DB included; source/link/root output rejected before write.
- V21: CI executes full Python 3.12 gate on `windows-latest`; release builds once read-only, then separate PyPI `id-token:write` and GitHub `contents:write` promotion jobs consume same artifact.
- V22: ∀ LLM chat → attempts ≤3; distinct HTTPX timeouts; each request timeout ≤ remaining total deadline; retry delay finite, `0..60s`, ≤ remaining; default total ≤900s; retry telemetry emitted.
- V23: ∀ persistent apply prompt/worker/job log → private no-follow creation + secret/credential redaction; Windows current-user DACL; log TTL default 30d; backup excludes logs unless explicit opt-in.
- V24: container base → immutable digest; app deps → `uv.lock --locked`; JobSpy exact hash; release emits SBOM + SHA256 checksums; separate no-checkout attestation job owns only required attestation/OIDC permissions.
- V25: apply agent ⊥ `browser_evaluate`; `RESULT:APPLIED` accepted only when last 3 nonempty agent lines = `SUBMISSION_ORIGIN:https://...`, `CONFIRMATION:<evidence>`, `RESULT:APPLIED`; claimed origin ∈ normalized job/application origins; mismatch → ⊥ applied. H-05 remains open: model report ≠ trusted browser event.
- V26: ∀ proxy/config/agent error surfaced to UI/log/DB → password/token/query secret redacted.
- V27: profile context cannot label lab/project years as professional; earned/completed wording requires explicit completed fact.
- V28: ∀ configured query: represented in tiered scorer intent or explicit target-family summary; `target_families` validated name + priority 1..3 and marked policy-only; `location_labels` matches `label||location`; unknown label → config error; no scope → all locations.
- V29: ∀ school with >12 courses: bounded summary includes academic-term newest + active-search-relevant courses, deterministically; no raw transcript text leak.
- V30: tailor instructions forbid assumed prior-role voice + mandatory invented quantification; source-backed metrics preserved only.
- V31: private career files + DB absent from Git diff; local config validates; post-migration DB integrity=ok; archived location-noise recoverable.
- V32: archived jobs are excluded from active discovery/enrichment/score/tailor/cover/apply queues, status, analytics, follow-ups, and pruning; archive count/history remains.
- V33: only valid target priority 1/2 can reach score 7+; priority 3/outside/missing or non-exempt low-hour work under full-time preference caps at 6 deterministically.
- V34: board remote tags are advisory; concrete place requires explicit posting remote evidence and cannot bypass location rejection; posting-tail caveats remain in bounded context.
- V35: skill present in paid source résumé cannot be labeled coursework-only merely because coursework also tags it.
- V36: stage `ok` requires no failed items; all-failed → error; mixed success/failure → partial; PDF conversion failures propagate; streaming terminates on bounded no-progress.
- V37: approved tailor persists job-unique `.txt` when inline PDF unavailable; warning-approved counts success; later PDF stage may supply sibling `.pdf`.
- V38: cover letter cannot relabel transferable front-desk/project work as paid IT/healthcare/field/ticket work or promise unverified location/schedule availability.
- V39: when structured transcript school facts exist, generated/scored education uses institutional GPA + earned-credit totals; stale profile values never reach documents.
- V40: validated cover mode never persists an exhausted failing draft; PDF failure persists a protected `.txt` fallback or increments stage errors.
- V41: every application uses current verified legal residence until moved; planned relocation may be stated only from explicit profile policy and never substitutes a former/planned address.
- V42: apply browser blocks document/XHR/fetch/websocket/event-source requests outside validated job/application origins; MCP config accepts only its sibling owned guard.
- V43: profile/resume/search/env/credential/SQLite(+WAL/SHM) files receive strict user-only permissions before read/write; failure is explicit without locking a nested source workspace.
- V44: strict tailor mode never promotes a judge-rejected résumé; review text/report remain private for manual inspection and DB path stays NULL.
- V45: retry report contains only current-attempt validator/judge state; résumé credits render only active-program total earned; target-appropriate skills heading survives PDF.
- V46: tracked-tree guard rejects all recognized private runtime/config/backup artifacts; private writes/copies fail on ACL error; tag verify runs Python audit; generic code has no candidate target constants.
- V47: ∀ pending score/tailor/cover stage S: `count(S)=len(select(S,limit=0))`; archive/description/score/retry/attempt/output gates cannot drift.
- V48: ∀ public example/test address fixture → explicit fictional street/city/state/postal sentinel; local privacy scan finds 0 exact profile/reference location collisions before publish.
- V49: ∀ release → project/runtime/tag version equal; version ∉ retired `0.4.2..0.4.8`; artifacts satisfy V46,V48 before publish.
- V50: ∀ local publish with private profile → tracked tree + wheel + sdist exact-collision count `0` for candidate/reference identity, location, employment, education, employer values; diagnostics ⊥ raw private values.
- V51: ∀ unit test crossing DB-backed orchestration → explicit initialized temp DB or mocked DB boundary; ⊥ default/user DB state.
- V52: ∀ cross-platform test → optional OS capability checked before use; unsupported symlink metadata operation cannot suppress portable core assertions or leak test artifacts.
- V53: ∀ tag release → `GITHUB_SHA` = fetched `origin/main` tip; stale ancestor tag ⊥ publish.
- V54: ∀ published dependency paths → no selectable extra resolves a known-vulnerable package; compatibility-only unsafe extras ⊥ ship.
- V55: ∀ supported JobSpy setup → exact hashed `1.1.82`; non-Markdownify requirements stay inside upstream bounds; metadata/import surface smoke passes; retired extra absent from project+lock.
- V56: editor load→save preserves query `location_labels`, location `label`, and schedule semantics (`part_time|full_time|any`); edited skills become runtime-authoritative without stale `skills_boundary` override.
- V57: resume parser retains every nonempty header contact line after optional title/location and before first body section; phone/email/social/portfolio data cannot vanish from PDF.
- V58: ∀ public pip install/update example → `--upgrade`; rerun over older DivApply cannot silently retain stale version.
- V59: nonnumeric/missing compensation cannot render as `$<prose>` or authorize numeric form entry; posted range preferred, else human review.
- V60: transcript DB retains all source facts; scoring/tailor coursework + inferred-skill context includes only completed positive-credit rows selected by active career relevance and explicit include/exclude policy.
- V61: positive apply signal cannot be blocked by bare degree/credential mention; hard mismatch iff explicit ineligibility or unmet non-substitutable required gap; preferred/substitutable alternatives remain eligible.
- V62: keyword extraction starts only on explicit requirement/preference signal and excludes compensation/benefit/EEO/application/self-ID boilerplate from required/preferred terms.
- V63: release build starts clean; wheel/sdist/release archives contain no runtime/build artifacts or nested distributions; private scan recursively inspects bounded nested archives.
- V64: per-market schedule/benefits/application policy cannot bleed across labels; current-market part-time gating cannot cap destination full-time fit, and `discovery_only` cannot auto-submit.
- V65: master résumé `ADDITIONAL EXPERIENCE` parses/renders as its own section; chronology lines cannot merge into another job or spill a lone education entry to page 2.
- V66: LLM job context ends before application/EEO/veteran/disability self-ID forms; protected-condition text cannot appear as matched/missing qualification evidence.
- V67: requirement headings/filler never become skill gaps; posting-declared equivalent experience plus LLM `Apply`/7+ remains 7+ even when reasoning omits the substitution phrase.
- V68: score reasoning preserves degree level + field separately; completed associate cannot be described as absent when only an IT-specific associate is absent.
- V69: dist gate binds exact project-version wheel+sdist; rejects every extra/symlink, unsafe/duplicate/case-colliding path, nonregular member, nested archive by name/magic, + bounded outer/member/count/expanded sizes; diagnostics redact member names.
- V70: release-evidence assembly re-runs V69 before copying any package; checksum/SBOM generation cannot bless invalid archive bytes.
- V71: release SBOM covers locked package graph + exact manual JobSpy runtime component/version/SHA-256 contract.
- V72: ∀ active recommendation → career-building target priority 1/2; food/retail/hospitality/warehouse/sales/generic customer-service title/keyword → reject/archive regardless score.
- V73: private direct-source crawl → official employer/agency registry; removed noisy source produces 0 targets; URLs remain validated HTTPS external targets.
- V74: schedule exception iff current job company exact-matches explicit `schedule_exception_employers|referral_employers`; `priority_employers`, posting text, résumé, + LLM output cannot create exception.
- V75: `application_mode=discovery_only` may preserve fit score but stored action reason ! state discovery-only + ⊥ immediate Apply recommendation.
- V76: `require_part_time` or `preferred_schedule=full_time` needs positive matching schedule evidence for score 7+; explicit conflict/unknown → cap 6 unless V74 exception; configured max-hours enforced iff present. `require_benefits` needs positive benefit evidence for 7+; V74 never bypasses qualifications/benefits.
- V77: bounded job context preserves opening + requirement-bearing middle windows + tail within limit after V66 stripping; truncation markers/compensation/location fragments ∉ keyword gaps.
- V78: aggregator discovery without verified direct employer/ATS URL → `source_verification=unverified_aggregator`, `application_mode=discovery_only`, score ≤6, ⊥ tailor/cover/apply; official feed/direct URL may become `official` only by deterministic origin evidence.
- V79: current-market part-time means employer-classified part-time; ⊥ invented default hour ceiling. Explicit `max_hours_per_week=N` requires posting evidence ≤N or manual review.
- V80: ∀ recursive release cleanup target/ancestor/descendant: symlink or Windows reparse point → fail before mutation; target remains repo-contained.
- V81: private/archive scanners enforce outer-size/member-count/expanded-byte budgets before materialization; tracked + nonignored untracked publishable files covered.
- V82: dist validator rejects file/ancestor conflicts, C0/C1 controls, + missing/unreadable project metadata fail closed.
- V83: each promotion download exactly equals checksum subject set; checksum verification precedes attestation/publish; post-build smoke cannot mutate attested bytes.
- V84: manual runtime SBOM component has stable `bom-ref` + root dependency edge.
- V85: stored matched skills are evidence-backed; negated/unverified/implied claims ∉ matches; all pre-V76 scores invalidated before use.
- V86: official trust/content transition atomically invalidates every unapplied score/evidence/document derivative before actionability; lower-trust outputs cannot survive promotion.
- V87: supported official ATS public API → deterministic validated adapter, no browser/CAPTCHA/LLM dependency; every redirect/job URL revalidated.
- V88: unavailable scoring modality has weight 0; remaining evidence weights renormalize to 1; absence ≠ negative evidence.
- V89: substitutable credential cannot persist as mandatory/missing in narrative/risk; equivalency stays human-reviewed; real evidence gaps retained.
- V90: tailored resume skill/claim must have candidate evidence; job-only requirement or recorded missing skill cannot enter candidate text. Cover generation reads exact persisted tailored artifact; missing/unreadable artifact fails closed.
- V91: generated resume header preserves verified current city/state when available; no street address or planned destination substituted.
- V92: untrusted ZIP EOCD/central-directory + decompressed TAR raw headers/pseudo-members pass bounded streaming preflight before `ZipFile`/`TarFile`; parser metadata cannot outrun configured count/byte caps.
- V93: distribution raw preflight + stdlib parse consume same continuously open verified file handle; path replacement cannot swap unchecked bytes into parser.
- V94: fresh-install audit invokes locked developer `pip-audit` by explicit project-venv path against smoke site-packages; runtime extra need not/shall not supply audit tooling.
- V95: 0.5.2 changed-method complexity check has no CodeFactor `Complex Method`/`Very Complex Method` finding; helper extraction preserves public behavior + V74-V94 gates.
- V96: bounded integer config accepts only non-bool integers/base-10 integer strings within range; Linux + Windows mypy gates pass.
- V97: ∀ configured official Phenom search/detail → embedded live job state parsed without LLM/browser; exact-origin job URLs validated; Apply-enabled refresh clears only synthetic expired failure state on unapplied reused requisition.
- V98: ∀ generated resume PDF → selectable text layer preserves ≥97% normalized source tokens + section order; one-column standard-heading DOM; failed ATS validation → ⊥ persist/upload.
- V99: schema.org `employmentType` scalar|array → canonical schedule token (`full_time|part_time|...`); serialized container text ∉ DB/scoring evidence.
- V100: verified professional IT experience=0 → resume/cover hands-on IT claim has preceding same-sentence lab/project/coursework anchor; no sentence attaches/bridges it to municipal/county/front-desk paid settings absent exact source evidence.
- V101: persisted cover has exact target title once + exactly 3 nonempty body paragraphs between salutation/sign-off.
- V102: official `availability_state=open` requires exact current listing + valid same-origin job/apply URL; generic landing/static/class-spec page cannot assert open.
- V103: `archive_reason=user` remains archived on rediscovery; exact verified-open refresh may reopen only `legacy|source_closed`; closed/unknown/unverified rows cannot reopen.
- V104: result concrete location re-resolves market policy; query target label cannot override conflicting result location or leak schedule/title policy across markets.
- V105: supported government boards bypass stale selector cache + LLM; bounded deterministic parser returns current jobs or authoritative zero, else fails closed.
- V106: current-market title policy permits configured non-fast-food part-time fallback; destination fallback/service titles cannot authorize active destination rows.
- V107: configured title include/exclude term → token/phrase-boundary match; `office` ≠ `officer`; `IT` ≠ substring inside another word.
- V108: enrichment stage never assigns fit score/irrelevance or skips a discovered row by hard-coded candidate title; discovery policy + scoring own relevance.
- V109: supported official-government detail URL → deterministic 200+ character job evidence + exact validated official listing/application entry; no LLM or arbitrary content-link promotion.
- V110: ambiguous tool name triggers fabrication guard only with technical context; season/date phrase `Spring 2026` ≠ Spring framework claim.
- V111: GovernmentJobs agency landing placeholder ≠ authoritative zero; validated same-origin agency fragment fetched + current cards deduped before availability decision.
- V112: structured job-description HTML/entities decoded to readable plain text before persistence/scoring; qualification wording retained, markup discarded.
- V113: bounded scoring context retains requirement bodies under Experience/Training/Education headings; linked qualification preamble alone ≠ sufficient evidence.
- V114: parsed résumé visible text <400 words → sparse one-column typography/spacing; content unchanged, exactly 1 page, + V98; layout code cannot add applicant claims.
- V115: before résumé validation, candidate-skill items absent from verified profile/base résumé evidence are deterministically removed; direct validator still rejects any survivor; empty required skills → retry/fail closed.
- V116: strict judge absence-only rejection naming quoted phrases all present in candidate evidence → auditable deterministic contradiction pass; any paid-work/context/fabrication issue or unquoted/unsupported phrase remains FAIL.
- V117: professional healthcare tenure=0 → any candidate `patient-facing *` claim fails; `confidential*` candidate claim requires exact profile/base résumé evidence; employer-requirement statement alone allowed.
- V118: professional IT tenure=0 → paid EXPERIENCE cannot add `service desk|help desk|ticket handling|ticket queue` absent exact base résumé evidence; target headline/role requirement ≠ paid-work proof.

## §T

|id|task|proof|status|
|---|---|---|---|
|T1|lock agent commands + env + MCP package/tool surface|focused launcher tests; V1–V3,V6|done|
|T2|make prompt fail closed for CAPTCHA/email authority|focused prompt tests; V5–V6|done|
|T3|isolate worker upload staging + cleanup|concurrency/lifecycle tests; V4|done|
|T4|stop automatic host Chrome-profile cloning|focused Chrome tests; V7|done|
|T5|harden redirect/DNS validation on manual URL fetch|SSRF redirect tests|done|
|T6|fix reliability-event transaction durability|close/reopen persistence test|done|
|T7|guard installer deletion + owned-port cleanup|path/process ownership tests|done|
|T8|raise CI assurance: coverage/types/action pins/reproducible deps|`test_ci_assurance` + `test_mcp_runtime`; V14–V16|done|
|T9|bind generated artifacts to job identity + guard shared legacy paths|`test_artifact_identity` + archive/apply regression; V18,I9|x|
|T10|keep transient scoring failures retryable|scorer + migration retry-state tests; V19,I10|x|
|T11|snapshot active SQLite DB into atomic verified backups|live-WAL + legacy-path restore tests; V20,I11|x|
|T12|add native Windows CI + split privileged release promotion|`test_ci_assurance`; V21|x|
|T13|add bounded typed LLM request/retry policy|fake-clock timeout/rate-limit tests; V22,I12|x|
|T14|harden private logs + retention + error/proxy redaction|security/maintenance/proxy tests; V23,V26,I13|x|
|T15|lock container inputs + emit release SBOM/checksums/provenance|CI assurance + local SBOM/checksum validation; V24|x|
|T16|remove page-JS agent tool + require structured submission proof|launcher/prompt injected/generic/wrong-origin proof tests; V25,I14|x|
|T17|add explicit career priorities + query/location scoping|config/scorer/crawl tests; V28,I16|x|
|T18|separate experience evidence + select relevant coursework + harden tailor voice|profile/coursework/prompt tests; V27,V29,V30,I15,I17,I18|x|
|T19|migrate local career data + enforce evidence/priority/location/stage/document integrity|backup + selfcheck + DB/stage/document report; V31-V38,I19-I23|x|
|T20|make structured transcript facts canonical + regenerate private artifacts|overlay tests + profile/resume reconciliation + regenerated packets; V39,I24|x|
|T21|fail closed on cover validation + preserve PDF fallback truthfully|generation/batch regressions; V36,V40|x|
|T22|enforce per-job apply-browser origin guard|owned init-page/config escape tests; V42,I26|x|
|T23|enforce private ACLs across existing user data|config/DB strict-permission regressions + live ACL audit; V43|x|
|T24|fail strict tailoring closed on judge rejection|strict/normal status + batch persistence regressions; V44|x|
|T25|tighten human career-quality presentation + retry trace|role heading/education/retry-state/PDF regressions; V45,I27|x|
|T26|close public release/privacy configuration gaps|artifact/ACL/config/release workflow regressions; V46,I28|x|
|T27|deepen pending-stage policy into DB boundary|selection/count parity + pipeline/cover migration; V47,I29|x|
|T28|replace copied location fixtures + add fictional-address guard|fixture regression + local profile-collision scan; V48|x|
|T29|retire contaminated distribution line + reserve clean `0.5.0`|version parity/retired-version test + PyPI/GitHub removal verification; V49|x|
|T30|add redacted tree/distribution private-value preflight|synthetic tree+wheel test + live private-profile scan; V50|x|
|T31|make launcher DB + symlink-retention regressions hermetic on Linux/Windows|focused launcher/maintenance tests + full OS matrix; V51,V52|x|
|T32|require tag release = current `main` tip|`test_v53_release_requires_exact_main_tip`; V53|x|
|T33|remove vulnerable JobSpy compatibility extra|secure-install contract + lock/audit checks; V54|x|
|T34|close residual JobSpy metadata/install drift|installer/CLI/lock/constraint + smoke checks; V55|x|
|T35|harden editor/profile-document/install boundaries|focused editor/PDF/prompt/docs regressions + full suite; V56-V59|x|
|T36|separate complete academic evidence from career-scoring context|selection/skill-map regressions + live transcript prompt audit; V60|x|
|T37|calibrate hard-gap + JD keyword boundaries|focused hybrid-scoring regressions + live IT canary; V61,V62|x|
|T38|close adversarial release-review drift|focused regressions + full preflight; V56-V60|x|
|T39|eliminate nested release/privacy artifact path|artifact-content + recursive-collision regressions; V46,V50,V63|x|
|T40|enforce market scopes across every discovery backend|SmartExtract/Workday scoped-target regressions; V28|x|
|T41|separate current-market apply policy from destination-market fit|typed resolver/config/prompt regressions + live rescore; V41,V64|x|
|T42|render compact prior-work chronology without layout corruption|parser/HTML regression + full-page PDF inspection; V65|x|
|T43|strip application self-ID boilerplate before all LLM document/scoring stages|shared-context regression + live Attain rescore; V62,V66|x|
|T44|calibrate Attain-style equivalent-degree + keyword headings|extractor/composite regression + targeted rescore; V61,V62,V67|x|
|T45|make score credential-gap wording field-precise|prompt contract + targeted rescore; V39,V68|x|
|T46|make release archive validator fully fail-closed|adversarial path/type/budget/version/nesting suite + canary; V63,V69|x|
|T47|include manual JobSpy runtime in CycloneDX evidence|SBOM component/hash regression; V24,V71|x|
|T48|enforce no-service career policy + refresh official source registry|config validation + target audit + active DB audit; V31,V64,V72,V73|x|
|T49|make score action policy structured + exact-employer scoped|spoof/priority/unrelated-employer/discovery-action regressions + live rescore; V33,V64,V74,V75,I32|x|
|T50|enforce deterministic schedule/benefit evidence + preserve middle requirements|focused context/composite/scorer regressions; V76,V77,V79,V85,I33|x|
|T51|persist discovery provenance + gate unresolved aggregators|schema/backend/stage regressions + live refresh audit; V73,V78,I34|x|
|T52|close recursive cleanup/release-evidence hardening gaps|Windows reparse/budget/path-set/SBOM regressions; V69-V71,V80-V84,V92-V94,I35|x|
|T53|retire stale score/action data + refresh official sources|verified backup, full active rescore/source audit, 0 stale actionable rows; V72,V73,V78,V85|x|
|T54|add deterministic official ATS adapters|Greenhouse API extraction/live refresh + URL/provenance regressions; V73,V78,V86,V87|x|
|T55|bind packet generation to candidate evidence + exact tailored artifact|job-only skill rejection, artifact-read, strict packet regeneration/visual QA; V38,V40,V85,V90|x|
|T56|pay down changed-method complexity debt|CodeFactor PR check + focused/full behavior parity; V95|x|
|T57|make Phenom discovery + generated PDFs deterministic/ATS-readable/truthful|Phenom current/reopen tests + schedule normalization + ATS extraction/order/render inspection + evidence-context/title/structure regressions + full gates; V73,V78,V86,V87,V97-V101,I36,I37|x|
|T58|repair official-government availability + market-specific discovery|GovernmentJobs/JobAps/CalCareers fixture/live canaries + archive/market/title/detail/document regressions + local DB repair; V32,V38,V64,V73,V78,V86,V101-V110,I38,I39|x|
|T59|repair async GovernmentJobs agency discovery|`test_v111_governmentjobs_agency_board_fetches_fragment` + false-zero/dedup regressions + Roseville live canary; V102,V105,V111,I39|x|
|T60|decode structured job descriptions before scoring|encoded JSON-LD qualification regression + target rescore; V38,V73,V112|x|
|T61|preserve government qualification bodies in score context|linked-preamble + Experience/Training truncation regression + target rescore; V38,V73,V113|x|
|T62|reopen live manual official jobs + improve truthful résumé generation/layout|official reopen + generation truth guards + sparse HTML/render/ATS QA; V38,V44,V90,V97,V98,V100,V103,V114-V118|x|
|T63|prepare privacy-clean 0.5.9 release|focused fixture + private tree/dist scan + locked preflight; V14,V48-V50,V63,V81-V84|x|

## §B

|id|symptom|cause|invariant|fix|proof|
|---|---|---|---|---|---|
|B1|7 launcher boundary regressions fail|untrusted-page agent got sandbox bypass + broad tools/env/MCPs|V1,V2,V3,V6|T1|`test_apply_launcher` security selection|
|B2|unknown MCP rejection emitted wrong diagnostic|required-server check ran before unknown-server check|V1|order validation|`test_agent_command_rejects_unknown_mcp_server`|
|B3|3 prompt authority regressions fail|prompt embedded solver workflow + advertised disabled tools|V5,V6|T2|`test_apply_prompt` authority selection|
|B4|Gmail opt-in/failure classification regressions fail|no central opt-in parser + email blocker retried|V6|T2|config + permanent-failure tests|
|B5|run ignored Gmail opt-in|prompt + MCP config independently defaulted off|V6|T2|run-job integration test|
|B6|touched-file lint failed|manual command re-imported module-level `shlex`|V8|remove local import|Ruff touched-file gate|
|B7|4 worker-isolation regressions fail|shared staging + app-root MCP + partial cleanup|V4|T3|prompt concurrency + run lifecycle tests|
|B8|cover staging assertion failed|legacy test omitted explicit worker dir after isolation change|V4|pass owned test dir|cover-upload test|
|B9|3 Chrome-profile isolation regressions fail|first run cloned host/peer data + trusted unmarked legacy|V7|T4|Chrome profile tests|
|B10|private redirect regression failed|manual fetch delegated redirects to HTTP client before validation|V9|T5|manual URL redirect test|
|B11|reliability event vanished after close|commit decision checked after INSERT opened transaction|V10|T6|close/reopen durability test|
|B12|environment dependency audit failed|floors allowed vulnerable PDF/CSS-selector patch versions; unrelated cache dep stale|V11|raise floors + upgrade env|metadata test + pip-audit|
|B13|retired solver still requested/advertised|wizard + doctor retained obsolete secret workflow after fail-close change|V5|remove onboarding/doctor path|wizard + CLI source tests|
|B14|wizard regression test raised `NameError`|new test split preceding test before its final assertion|V8|restore assertion scope|wizard tests|
|B15|occupied-port/installer regressions fail|cleanup killed unowned listener + recreate accepted escaping path|V12,V13|T7|Chrome + installer safety tests|
|B16|mypy baseline found 39 errors in 11 files|⊥ static type gate; unchecked `None` + cross-branch type reuse accumulated|V14|T8|mypy Linux+Windows|
|B17|locked-runtime regression import failed + source retained `npx`|MCP transitives resolved at each run without repo integrity tree|V15|T8|`test_mcp_runtime`|
|B18|real locked-tree audit found 4 High advisories|archived Gmail MCP `1.1.11` ships obsolete runtime deps + `mcp-evals`|V6,V16|retire Gmail MCP; Playwright-only lock|npm audit + fail-closed tests|
|B19|`FIT_SCORE: unavailable` parsed as `1`|mypy narrowing set `0`, then unconditional minimum clamp raised it to `1`|V17|clamp only matched numeric value|`test_parse_score_response_keeps_missing_numeric_score_at_zero`|
|B20|same source+title jobs overwrite resume/cover files|artifact name omitted stable job identity|V18|T9|`test_artifact_identity`|
|B21|temporary LLM outage durably hides job at score `0`|exception result indistinguishable from valid score + persisted `scored_at`|V19|T10|scoring retry-state tests|
|B22|successful backup omits WAL commits or legacy active DB|ZIP copied raw configured DB path instead of SQLite active snapshot|V20|T11|live-WAL + legacy restore tests|
|B23|generic transcript phrase can authorize `APPLIED`|parser scans any output line for weak confirmation phrase|V25|T16|structured confirmation tests|
|B24|T14 contract tests fail collection|private-log + retention interfaces absent|V23,V26|T14|security + maintenance focused tests|
|B25|T15 release-evidence tests fail collection|SBOM/checksum builder absent|V24|T15|release evidence + CI assurance tests|
|B26|CI JobSpy hash contract fails|smoke install used mutable package name|V24|T15|CI assurance exact-wheel test|
|B27|installer/docs JobSpy pin tests fail|bootstrap + examples retained mutable package name|V24|T15|installer/docs contract tests|
|B28|stale wheel enters release bundle|evidence builder accepted every prior `dist/*` artifact|V24|T15|duplicate-distribution rejection test|
|B29|10 T16 boundary tests fail|weak phrase scan + page JS tool/prompt surface remain|V25,I14|T16|launcher + prompt proof tests|
|B30|3 T17 intent/scope regressions fail|search config lacks priority/scope validation; scorer truncates 20; crawl builds full Cartesian product|V28|T17|config + scorer + crawl focused tests|
|B31|T17 full mypy gate fails|YAML priority `Any` passed directly to `int` without typed conversion boundary|V28|T17|string-normalize after bool guard; mypy|
|B32|5 T18 evidence/prompt regressions fail|course summary is insertion-order first-12; IT years/cert status ambiguous; prompt demands prior-role voice + metrics|V27,V29,V30|T18|profile/coursework/tailor focused tests|
|B33|personalized search config fails validation|YAML flow-list city/state scalars with commas were unquoted + split into tokens|V31|T19|quote scoped labels; config validation|
|B34|status/rescore still count archived noise|stats + most stage predicates omit active-row boundary|V32|T19|active stats/stage regression tests|
|B35|full retry-state test fails on archive predicate|minimal hand-built jobs fixture omitted production `archived_at` column|V32|T19|align fixture schema; full suite|
|B36|direct rescore/tailor/cover/apply/enrich paths can process archived rows|stage helper fixed but hand-written SQL bypasses it|V32|T19|direct-stage archive regressions + source audit|
|B37|4 apply-queue tests fail archive predicate|minimal apply fixtures omit production `archived_at` column|V32|T19|align apply fixture schemas; full suite|
|B38|seasonal/PT/generic fallback jobs remain score 7|target policy supplied but no explicit 7+ queue eligibility rule|V33|T19|priority/schedule prompt-context tests + live rescore|
|B39|P3 customer-success fallback still scores 7|prompt-only cap unenforced; response omits machine-readable family priority|V33|T19|structured `TARGET_PRIORITY` + composite caps|
|B40|out-of-market campus/desk-side jobs stored as remote|board boolean trusted without explicit posting evidence|V34|T19|remote-tag contradiction/evidence tests|
|B41|remote focused test fails with undefined crawl locals|new test split preceding scoped-crawl assertions|V34|T19|restore test scope; focused suite|
|B42|strict tailor rejects paid accounting as coursework-only|JSON validation omits original résumé evidence|V35|T19|validator original-text regression|
|B43|tailor/cover stages report `ok` on zero success|pipeline wrappers discard runner counts|V36|T19|stage status regression tests|
|B44|PDF stage reports `ok` after every conversion fails|batch converter logs + swallows item exceptions|V36|T19|conversion failure propagation test|
|B45|PDF propagation test raises `NameError`|new test omitted `pytest` import|V36|T19|import pytest; focused test|
|B46|4 warning-approved résumés exist but DB reports 0|approved count omits warning status; PDF failure discards `.txt` pointer|V37|T19|fallback artifact persistence test|
|B47|generated covers imply paid IT/healthcare/field/ticket work + immediate CA presence|cover prompt says never invent but lacks explicit transferable-experience/location boundary|V38|T19|cover prompt/zero-professional-IT validator tests + regenerate|
|B48|regenerated covers still merge paid work with patient/device/field IT claims|semantic boundary lacks healthcare + cross-context phrase cases; salutation can repeat name|V38|T19|cover boundary/polish regressions + targeted regenerate|
|B49|IT covers imply municipal/customer-service roles supplied end-user IT support|validator catches named claims but not sentence-level context joins|V38|T19|real-output context-join regressions + targeted regenerate|
|B50|new transcript import conflicts with profile + 8 tailored résumés|profile education injected verbatim; import feeds coursework only|V39|T20|canonical education overlay test + regenerate all artifacts|
|B51|strict-invalid cover is DB-linked; PDF failure reports zero errors|generator returns exhausted draft; batch drops protected text fallback|V40|T21|exhausted-validation + PDF-fallback regressions|
|B52|private QA renders + real applicant/reference fixtures enter publishable tree|no `/tmp/` ignore/staging gate; tests copied live profile data|V31|T19|anonymized fixtures + tracked-artifact CI guard|
|B53|California cover headers show Utah while forms use California|job-address selection exists only in apply prompt|V41|T20|shared selector + generation/PDF address regression|
|B54|`City, ST (Remote)` board labels bypass explicit-remote evidence|classifier returns true on any location remote token|V34|T19|concrete tagged-location regression + active DB cleanup|
|B55|work-arrangement/qualification tail is hidden from scoring/docs|job context truncates description prefix only|V33,V34|T19|bounded head+tail context regression|
|B56|missing/malformed `TARGET_PRIORITY` can retain score 7+|deterministic cap recognizes only explicit 3/outside|V33|T19|missing-priority fail-closed cap regression|
|B57|archiving can race a claimed application and later stage writes|archive accepts `in_progress`; persistence updates omit active guard|V32|T19|in-progress archive refusal + guarded persistence|
|B58|archived jobs remain in due follow-ups/lifecycle analytics|queries omit active-row boundary|V32|T19|archived lifecycle regression|
|B59|streaming workers can spin forever/overwrite partial status|pending SQL drifts from eligibility; no no-progress guard; final status forced `ok`|V36|T19|pending alignment + partial/stagnation regressions|
|B60|enrich/score wrappers report `ok` despite returned item errors|wrappers discard runner stats|V36|T19|wrapper status regressions|
|B61|job-page prompt injection can navigate applicant PII to arbitrary origin|navigation restriction is prompt-only|V42|T22|per-job context route + config ownership validation|
|B62|existing profile/env/credentials/DB inherit broad local ACLs|protection occurs only on selected new outputs; credential failures swallowed|V43|T23|file strict protection + live remediation|
|B63|archive artifact test errors on missing `apply_status`|minimal fixture predates in-progress archive guard|V32|T19|align fixture schema|
|B64|2 positive-signal score tests cap at 6|legacy fixtures omit newly mandatory target priority|V33|T19|add explicit P1 evidence|
|B65|normal temp cleanup deletes durable PDF|race cleanup broadened shared temp helper suffixes|V18,V32|T19|separate unpersisted-output cleanup|
|B66|strict judge-rejected résumés are promoted and review report deleted|last retry maps rejection to warning-success unconditionally|V44|T24|mode-aware final status + preserve review files|
|B67|judge rejects allowed target headline/skill omission/canonical education|judge rules mention allowances but coherence criteria contradict them|V44|T24|explicit precedence rules + rerun strict review|
|B68|judge cannot verify canonical education and rejects all 7 outputs|judge prompt asserts profile authority but omits profile education evidence|V39,V44|T20,T24|canonical education block + program-field overlay|
|B69|strict judge flags unlabeled education and generated text contains malformed fragments|evidence block is positional; prompt lacks channel-claim guard; text validator misses dangling conjunction/year punctuation|V39,V44|T20,T24|labeled education evidence + channel guard + malformed-fragment regressions|
|B70|direct strict canary exits before model call|library runner was invoked without CLI `load_env()` bootstrap|V44|T24|load private env before direct targeted run; confirm no DB path persisted|
|B71|full rescore command is terminated after 10 seconds|shell deadline was set as operation timeout instead of yield interval|V31,V36|T19|rerun in long-lived cell; inspect partial progress and final counts|
|B72|later validation failure retains prior-attempt judge finding|retry report object is reused without clearing stage results|V45|T25|reset current-attempt stage fields; staged-retry regression|
|B73|strict-pass service résumé remains IT-heavy + prior schools show partial credits|fixed technical heading/schema; education prints any transcript unit fallback|V45|T25|allowlisted role heading + total-credit scope/current-program rule + PDF regression|
|B74|judge rejects exact profile skills while core résumé keeps irrelevant lab content|allowed-skill evidence is dense/ambiguous; core-heading project/category guidance weak|V44,V45|T24,T25|labeled exact-skill evidence + core-role relevance rules; targeted strict rerun|
|B75|core résumé relabels public service as government-user support/customer follow-up; judge fails despite “no definitive fabrication”|transferable-context noun guard + judge decision threshold missing|V38,V44,V45|T24,T25|public-service label guard + concrete-evidence verdict rule; targeted strict rerun|
|B76|human PDF gate finds irrelevant core-role cloud project + “Provisioned and administer”|core project rule is prompt-only; validator misses mixed-tense compound verb|V45|T25|deterministic core-project drop + mixed-tense regression; regenerate top packets|
|B77|Greka strict run repeats identical mixed-tense phrase on 3 attempts|prompt correction is nondeterministic for a known mechanical defect|V45|T25|narrow sanitize rewrite + validator backstop; targeted rerun|
|B78|DMS desktop/hardware packet selects cloud project over verified PC build|project guidance says relevant but gives no tie-break by duty family|V45|T25|hardware-vs-server project selection rule; targeted regenerate|
|B79|strict Greka cover says target work was already done “in the field”|zero-professional-IT guard misses generic field-tenure wording|V38,V40|T21|field-tenure phrase guard + prompt regression; targeted regenerate|
|B80|replacement Greka cover opens with “background in end-user support”|generic background claim detaches IT duty from project/transferable context|V38,V40|T21|zero-IT end-user-background guard + prompt regression; targeted regenerate|
|B81|iWorQ cover calls verified resident/public-counter work “client-facing”|target-job noun leaks backward into candidate experience|V38,V40|T21|client-context evidence guard + prompt regression; targeted regenerate|
|B82|replacement iWorQ cover says follow-up calls match prior work + “same problems from both sides”|missing target duty framed as experience; vague equivalence escapes channel guard|V38,V40|T21|missing-channel transfer rule + equivalence phrase guard; targeted regenerate|
|B83|iWorQ closing says virtual training/follow-up “matches service I have done”|channel matcher omits `done` experience verb|V38,V40|T21|add done variant + exact regression; targeted regenerate|
|B84|channel regression still passes because `call` matches inside `municipal`|evidence authorization uses raw substring membership|V38,V40|T21|word-boundary channel evidence matching; municipal regression|
|B85|master résumé page 2 renders `Â·` in education details|PDF HTML separator contains double-decoded UTF-8 literal|V31,V45|T20,T25|use HTML `&middot;` entity + render regression; regenerate base PDF|
|B86|master PDF bolds wrapped bullet fragments as job titles + nests projects under experience|entry parser discards indentation; base project heading lacks alias|V31,V45|T20,T25|join indented bullet continuations + project-heading alias; regenerate/visual QA|
|B87|forced tracking of credentials/backups/logs/private config passes CI|artifact guard enumerates only 8 paths/names|V46|T26|expanded deny catalog + `.gitignore` coverage|
|B88|wizard/migration/backup sensitive creation can suppress ACL failure|private helpers/call sites default non-strict; copy occurs before protection|V43,V46|T23,T26|strict defaults + protected copy/write paths + failure regressions|
|B89|generic package hardcodes candidate CA/Sutter/site targets|address/priority/site policy lives in source constants/config|V46|T26|profile/search selectors + generic marker policy + private site override|
|B90|tag verification audits npm but not Python dependencies|publish workflow omits `pip-audit` despite installed locked dev tool|V46|T26|release audit step + assurance regression|
|B91|4 artifact tests fail after DB-owned pending selection|hand-built jobs table omits production ordering column `discovered_at`|V47|T27|align fixture schema/data; full suite|
|B92|release diff gate fails on generic site registry|edit leaves a blank line at EOF|V8,V46|T26|remove trailing blank; rerun diff gate|
|B93|private site/employer overrides retain inherited admin/system ACLs|root sensitive-file hardener omits `config/*.yaml`|V43,V46|T23,T26|strict-protect user config on resolution + live ACL audit|
|B94|public example/tests reuse private postal/locality values|fixtures copied real profile/reference locations; artifact guard checks paths/direct identifiers only|V48|T28|fictional sentinels + address-fixture CI guard + local collision scan|
|B95|fictional-location focused test leaves preserved location expectation stale|fixture rewrite changed source record but not submitted search/input pair|V48|T28|align input + expected fictional locality; focused suite|
|B96|PyPI `0.4.2..0.4.8` artifacts contain candidate-specific data; source still reports `0.4.8`|legacy releases predate private/public boundary; package version not advanced after retirement|V49|T29|delete old distributions + bump `0.5.0` + version parity guard|
|B97|3 full-suite tests retain one real-location side after bulk fixture cleanup|exact city-state variants differ by case/comma or live inside input JSON|V48|T28|align fictional input/expected pairs; focused + full suite|
|B98|2 focused fixture tests still mismatch after B97|dashboard search normalizes case; dedup test has second canonical-key assertion|V48|T28|align normalized expectation + every duplicate input/assertion|
|B99|clean `0.5.0` sdist still includes private school value|location-only scan omits education/employment/identity artifact surface|V50|T30|general redacted tree+distribution collision scanner + live preflight|
|B100|pristine CI launcher test errors `no such table: jobs`|test patched app paths but implicitly opened default DB; local private DB masked missing fixture|V51|T31|initialize + inject temp DB; focused/full matrix|
|B101|Windows retention test raises `NotImplementedError` before assertions|test assumes no-follow symlink `utime` exists; Windows lacks capability|V52|T31|capability-safe optional symlink fixture cleanup; focused/full matrix|
|B102|artifact-collision integration test silently opens user DB|mocked guard hid eager default `get_connection()` evaluation|V51|T31|inject fixture DB + exercise real collision guard before staging|
|B103|tag release accepts stale `main` ancestor|guard checks ancestry, not exact current tip|V53|T32|`test_v53_release_requires_exact_main_tip`|
|B104|Dependabot flags runtime `markdownify<0.14.1`|compatibility-only `jobspy-upstream` extra keeps unsafe transitive lock path|V54|T33|secure-install contract + lock/audit checks|
|B105|retired extra survives in lock markers|obsolete `[tool.uv].conflicts` retained removed extra identity|V54,V55|T34|lock text absence regression|
|B106|Unix installer + doctor suggest mutable JobSpy|exact hashed contract covered PowerShell/CI only|V24,V55|T34|all install-surface pin/hash regression|
|B107|fresh `full` may resolve pandas 3/regex 2025+|secure floor omitted upstream non-Markdownify upper bounds|V55|T34|metadata bound + callable JobSpy smoke regression|
|B108|runtime validator passes broken JobSpy import|metadata-only validator replaced prior import smoke|V55|T34|public API import success/failure regressions|
|B109|`divapply edit` drops scoped-market labels + leaves schedule contradictory + skill edits inert|text codecs omit advanced fields; schedule derives from one legacy bool; runtime prefers untouched `skills_boundary`|V56|T35|round-trip fixtures + synchronized representations|
|B110|master PDF omits phone/email/GitHub/site when title precedes multiline contacts|parser keeps only one contact line in titled header|V57|T35|multiline-header parse/render regression|
|B111|user follows published install commands but remains on 0.4.8|pip examples omit `--upgrade`; satisfied installed package is not refreshed|V58|T35|public-install contract regression|
|B112|application prompt emits `$Use the employer's posted range...`|prompt assumes salary field is numeric and prefixes raw profile prose|V59|T35|numeric/prose compensation prompt regressions|
|B113|scoring context injects Swimming/Music/orientation + broad inferred skills|newest-course half and all-row skill aggregation ignore career relevance/exclusion policy|V60|T36|shared selected-row filter; live context audit|
|B114|0.5.2 private-collision preflight finds candidate/education locality in public editor test|new scoped-search fixture copied live market names|V48,V50|fictionalize fixture|tree+wheel+sdist collision scan|
|B115|LLM says apply/7 but composite gives 5 for equivalent-experience IT role|bare `degree` token classified as hard mismatch despite accepted substitute|V61|T37|hard-gap evidence model + equivalency regression/live rescore|
|B116|EEO/disability/form text becomes required keyword misses|generic `skills` starts sticky required bucket; no non-job boundary|V62|T37|explicit section signals + boilerplate reset/stop regressions|
|B117|unknown/unfinished coursework enters career context; importer drops status|completion accepts missing/non-finite facts; import omits status|V60|T36,T38|strict completion predicate + status import regressions|
|B118|doctor can preserve stale installed release|runtime remediation omits `--upgrade`|V58|T35,T38|upgrade command regression|
|B119|editor saves legacy part-time policy as full-time while runtime stays constrained|schedule codec omits legacy bool/hour aliases|V56|T35,T38|legacy round-trip regressions|
|B120|blank-separated social links vanish from PDF|header scan stops at first blank before known body section|V57|T35,T38|blank-tolerant contact regression|
|B121|malformed coursework policy silently disables filter|validator omits coursework policy types/ranges|V60|T36,T38|fail-closed validation regressions|
|B122|huge numeric compensation crashes prompt|unbounded float/round conversion overflows|V59|T35,T38|bounded finite parse regression|
|B123|scope labels containing codec delimiters do not round-trip|editor uses unescaped `|`/`;` serialization|V56|T35,T38|escape/validation round-trip regression|
|B124|local sdist contains `.coverage`, release bundle, and nested stale sdist with private fixtures|build reuses dirty output; sdist has no explicit excludes; scanner decodes nested archive as text only|V46,V50,V63|T39|clean build + explicit excludes + bounded recursive scan regression|
|B125|recursive scanner test fails during dynamic module import|`dataclass` resolves postponed annotations through absent `sys.modules` entry|V63|T39|dependency-free budget class; focused regression|
|B126|fictional-user guard flags its own prefix assertion|sentinel path omitted terminal separator required by guard|V48|T39|use complete fictional path prefix; focused regression|
|B127|preflight cleanup deletes fresh evidence after validation|helper insertion matched late block instead of pre-build boundary|V63|T39|order assertion + move cleanup before build; erase coverage after report|
|B128|blank-separated LinkedIn line is mistaken for body heading|header scan uses permissive all-caps heuristic whose normalized input is always uppercase|V57|T35,T38|recognized-heading-only header boundary; focused regression|
|B129|destination queries search current market; scoped queries run across unrelated Workday employers|SmartExtract uses first location; Workday drops query labels|V28|T40|shared scoped pairs + employer market labels; focused/live target audit|
|B130|destination fit inherits current-market part-time gate; prompt says candidate cannot relocate|one global schedule + hardcoded relocation text|V41,V64|T41|typed market overlay + explicit relocation/application-mode regressions|
|B131|additional-experience lines merge into one malformed job and push one school to page 2|section alias/render path missing|V65|T42|dedicated compact-section regression + re-render|
|B132|Attain score is 7 but disability conditions appear as missing skills|LLM context still carries ATS self-ID tail after local keyword extractor stops|V62,V66|T43|shared context truncation + targeted live rescore|
|B133|sanitized Attain rescore falls to 6 and emits `qualifications & education`, `e.g` as gaps|posting substitution invisible to hard-gap detector; headings/filler enter keyword candidates|V61,V62,V67|T44|job-text-aware substitution + heading/filler regressions|
|B134|Attain risk says `no completed associate/IT degree` despite completed general-studies associate|prompt does not separate credential level from field|V39,V68|T45|degree-field precision instruction + targeted rescore|
|B135|clean canary passes checker that accepts archive bombs, path collisions, ZIP devices, stale pairs, + renamed nested archives|validator normalizes/ignores unsafe state and lacks budgets/project binding|V63,V69|T46|fail-closed validator rewrite + adversarial suite|
|B136|evidence assembler accepts invalid wheel/sdist bytes when standalone gate is skipped|assembly validates names/counts/checksums only|V69,V70|T46|invoke content validator before bundle mutation|
|B137|CycloneDX evidence omits maintained manually installed JobSpy runtime|uv export sees only declared package graph|V24,V71|T47|supplement exact component/version/hash before validation|
|B138|noisy aggregator remains enabled after service-job cleanup|broad source outruns title policy + consumes crawl budget|V72,V73|T48|remove source; add verified official current/destination feeds|
|B139|full preflight stops before tests on 3 mypy errors|optional `Any` passed to numeric constructors + education local shadows header string|V14|T38,T42|normalize through string boundary + rename local; Linux/Windows mypy|
|B140|cover address integration expects unverified destination address|legacy fixture omits required current-legal-residence evidence|V41|T41|mark alternate fixture verified; focused/full suite|
|B141|private collision gate blocks 2 SPEC city references|career-policy research reintroduced candidate geography into tracked docs|V46,V50|T48|replace with market-neutral terms; tree+dist scan|
|B142|priority employer can weaken current-market part-time gate|LLM context conflates ranking preference with schedule exception; exception inferred from untrusted text|V33,V64,V74|T49|trusted exact-employer bool into context/composite; rescore|
|B143|destination score-7 rows say Apply despite discovery-only market|action wording left to LLM while only apply stage enforces mode|V64,V75|T49|deterministic discovery-only action reason after fit scoring; rescore|
|B144|current full-time/unknown + destination low-hour/no-benefit roles reach 7|schedule/benefits exist only in prompt prose|V76,V79|T50|structured evidence caps; remove invented private hour limit; rescore|
|B145|middle minimum qualifications disappear (false Jobot 7)|head/tail truncation discards requirement section|V77|T50|bounded requirement windows + keyword cleanup|
|B146|aggregator rows become actionable from partial text|DB lacks origin market/query/mode/official verification|V78|T51|persist provenance; stage/actionability gates|
|B147|release cleanup can cross NTFS junction|lexical containment rejects symlink only, not Windows reparse points|V80|T52|reject reparse target/tree before recursive delete|
|B148|scanner/promotion/SBOM evidence still trusts unbounded/unlisted bytes|resource/path-set/graph checks incomplete|V81-V84|T52|bounded iteration + exact subjects + SBOM edge|
|B149|LLM matched fields claim implied/negated skills; all 15 active scores stale|free-text matches persisted without evidence boundary + changed context|V85|T50,T53|sanitize matches + invalidate/full rescore|
|B150|0.5.1 upgrades retain stale scores/documents after V76|private cleanup only; no versioned policy invalidation|V85|T53|v5 migration clears unapplied score/document pointers; preserves application history|
|B151|actionability regression test reports zero official documents|fixture accepts path overrides but omits them from INSERT; cleanup call unqualified|V78|T51|persist all fixture fields; rerun focused gate|
|B152|blank-location role can auto-apply; destination remote inherits current schedule|market resolver conflates missing with broad remote and ignores persisted query market|V64,V76,V78|T50,T51|fail blank/conflicts closed; exact persisted remote-market regression|
|B153|part-time agent answers below target from range midpoint|pay prompt ignores numeric hourly target/floor|V41,V76|T50|clamp target to posted range; below-floor human-review regression|
|B154|stored voluntary EEO attributes are auto-submitted without consent|storage conflated with disclosure authorization|V40,V41|T51|explicit opt-in flag default false; prompt redaction regression|
|B155|official Greenhouse refresh hits anti-bot page then needs LLM key|generic browser extractor ignores public jobs API|V73,V87|T54|deterministic API adapter; live refresh|
|B156|official refresh can inherit stale manual score/documents|trust promotion updates provenance but not derived fields|V78,V85,V86|T51,T54|atomic invalidation on unapplied promotion regression|
|B157|official refresh can erase unchanged score/packet or trust cross-host API URL|unconditional invalidation + board token not bound to returned URL|V86,V87|T54|null-safe change gate + same-board URL regression|
|B158|official role gets keyword 0 + markup-truncated context|Greenhouse description is HTML-escaped HTML; adapter parses only once|V77,V85,V87|T50,T54|entity decode before HTML-to-text; live rescore|
|B159|unparseable/no-keyword posting gets artificial 30% zero penalty|composite weights missing modality as negative evidence|V85,V88|T50|availability-aware weight renormalization regression|
|B160|verified setup/user-assistance/troubleshooting appear missing; model invents paid requirement|literal phrase matching + weak equivalency instruction|V61,V68,V85|T50|bounded evidence synonyms + no-unstated-requirement prompt regression|
|B161|score narrative still calls accepted degree alternative unmet|free-form LLM text bypasses substitution-aware composite|V68,V85,V89|T50|deterministic narrative sanitizer + real-gap preservation regression|
|B162|persisted explanation contradicts deterministic hit/gap evidence|free-form LLM still authors dashboard reasoning|V85,V89|T50|derive stored reasoning only from bounded hits/gaps/score/substitution|
|B163|strict cover exhausts retries; batch uses master resume despite persisted tailored artifact|stochastic high-temperature draft + wrong evidence input|V38,V40,V90|T55|low-variance retry + exact tailored-artifact reader regressions|
|B164|tailored resume inserts posting-only `asset tracking`, the recorded gap|validator authorizes job vocabulary without candidate evidence|V85,V90|T55|reject candidate-unsupported/job-only skill claims; regenerate packet|
|B165|remote tailored resume drops current city/state|assembler intentionally omits verified location|V41,V91|T55|inject current city/state only; render regression|
|B166|cover lifecycle tests patch removed master-resume input|fixtures bypass exact tailored-artifact contract|V90|T55|owned artifact fixtures/helper patch; focused rerun|
|B167|pending-stage fixtures vanish after actionability gate|fixtures omit official/active provenance|V47,V78|T51|persist trusted provenance in eligible rows; parity rerun|
|B168|tailored text has city/state but PDF header drops it|renderer ignores parsed `location` field|V91|T55|render location with contact; PDF regression/regenerate|
|B169|cover says technical skills apply `across public-sector and lab settings`|validator misses ambiguous cross-setting aggregation|V38,V90|T55|reject aggregated attribution; explicit paid-vs-lab prompt/regenerate|
|B170|cover relabels target title as `IT Support Specialist training`|job-title context leaks into education claim|V27,V90|T55|exact program-name rule + target-title-as-training rejection/regenerate|
|B171|cover groups IT skills as built through lab + public-sector roles|guard covers `across` wording, not mixed-setting sentence structure|V38,V90|T55|zero-IT mixed-setting sentence rejection + regenerate|
|B172|cover fuses Docker home-lab fact into separate website project|profile project names/tools lack association boundaries|V38,V90|T55|exact-tailored project anchors only; unseen-domain rejection|
|B173|employer sector list becomes claimed healthcare/nonprofit work context|company context leaks backward into candidate experience|V27,V38,V90|T55|sector-evidence guard + separate-company-context prompt|
|B174|cover maps City records work to `asset-tracking discipline`|known missing skill re-enters as transferable claim + hyphen evades exact check|V85,V90|T55|persisted-gap alias guard + gap block in prompt|
|B175|one cover sentence assigns escalation to City + county work|duties aggregate across distinct paid roles|V38,V90|T55|one paid setting/employer per sentence; mixed-setting rejection|
|B176|6 release-hardening regressions fail: untracked files skipped, outer archives read unbounded, TAR members materialized, C1 paths accepted, file/ancestor conflicts accepted, missing project version ignored|V81/V82 contracts were specified before scanner enforcement|V81,V82|T52|bound/read incrementally; scan cached+nonignored untracked; reject unsafe path graph/metadata absence; rerun focused gates|
|B177|expanded V81/V82 suite exposes 9 more unsafe paths: extensionless files skipped; ignored distinction absent; directory floods uncounted; ZIP/TAR payloads read after aggregate failure; reverse/casefold conflicts accepted; non-string/nonregular metadata accepted|scanner validation is sequential and name-only instead of atomic metadata preflight + typed path graph|V81,V82|T52|preflight bounded metadata before extraction; enumerate publishable set; typed casefold graph; strict string metadata|
|B178|7 release-evidence tests fail before SBOM assertions after V82 closes missing-metadata path|isolated distribution fixture relied on implicit absent `pyproject.toml` acceptance|V82,V84|T52|fixture writes exact project version; retain one explicit missing-metadata regression; rerun SBOM tests|
|B179|5 V83/V84 regressions fail: JobSpy lacks stable ref/root edge; rootless graph passes; semantic tamper + duplicate manifest subject pass verification|supplementer returns on component match and checksum verifier validates only digest-set equality|V83,V84|T52|normalize component+graph; semantic SBOM verification; reject duplicate manifest keys|
|B180|rootless-SBOM regression raises generic supplement error instead of typed root-component failure|metadata lookup is inside broad parse exception|V84|T52|parse base payload first; validate root metadata separately|
|B181|release assurance test loses `pip-audit --path` contract after smoke-venv relocation|absolute executable spelling bypasses existing policy assertion despite active isolated venv|V24,V83|T52|invoke activated `pip-audit --path`; rerun workflow assurance|
|B182|ad-hoc clean-install smoke stops at `pip check` after JobSpy runtime succeeds|upstream 1.1.82 metadata deliberately pins vulnerable Markdownify; supported secure install overrides it via hashed `--no-deps`|V24,V54,V55|T34|retain documented intentional warning; verify with runtime-bound validator + path audit, not `pip check`|
|B183|V81 re-audit finds ZIP central directory + TAR PAX/GNU payload can allocate before logical budget loop|stdlib constructors parse metadata before `infolist`/iteration returns control|V81,V92|T52|raw EOCD/CD + streaming TAR header preflight; constructor-not-called regressions|
|B184|8 constructor-level V92 regressions fail across private + distribution scanners|no raw ZIP/TAR metadata preflight or metadata-byte cap exists|V92|T52|implement fixed-header streaming preflight; reject extension pseudo-members; rerun gates|
|B185|V92 focused suite fails during scanner import|`BinaryIO` imported from `collections.abc`, where Python 3.12 does not expose it|V92|T52|import typing-only protocol from `typing`; rerun same focused suite|
|B186|V92 adversarial re-audit swaps distribution after preflight and bypasses ZIP metadata/TAR extension rejection|scanner closes verified handle then reopens mutable path for stdlib parser|V93|T52|swap-on-close ZIP/TAR regressions; one handle from preflight through parse|
|B187|2 V93 swap-on-close regressions parse replacement ZIP/TAR contents|stdlib constructors still receive mutable path after verified handle closes|V93|T52|rewind + parse same live handle; rerun release gates|
|B188|local fresh-install smoke cannot find `pip-audit` inside clean runtime venv; release workflow also invokes it bare|auditor is dev-only + `setup-uv` does not activate synced `.venv` by default|V94|T52|assert/use `.venv/bin/pip-audit --path` in release smoke; rerun assurance|
|B189|V94 workflow regression fails|publish smoke references unqualified auditor absent from clean runtime venv|V94|T52|invoke locked `.venv/bin/pip-audit` against smoke path; rerun release tests|
|B190|V93 re-audit swaps archive after path `lstat` but before open; oversized replacement passes|regular/reparse/outer-size checks are not repeated/bound on live descriptor|V93|T52|live `fstat` + post-open path/descriptor identity; lstat-to-open ZIP/TAR regressions|
|B191|2 live-handle V93 regressions accept oversized replacement ZIP/TAR|opened descriptor metadata is unchecked|V93|T52|shared descriptor verifier before raw preflight; rerun release gates|
|B192|PR #11 CodeFactor fails with 12 complex + 1 very-complex changed method|policy/scoring/discovery/release logic accumulated multi-branch orchestration|V95|T56|extract cohesive helpers; preserve tests/security gates; rerun CodeFactor|
|B193|release preflight stops on `_bounded_integer(object)` mypy error|helper annotation exposed unchecked numeric coercion + float acceptance|V96|T56|fail-closed scalar narrowing + named regression; rerun both mypy gates|
|B194|live reused Sutter requisition absent/stale-inactive|generic dynamic-site extraction lacks Phenom DDO adapter; official refresh preserves synthetic expired apply failure|V97|T57|deterministic adapter + reopen regression + live refresh|
|B195|PDF may look polished but ATS parse unverified|two-column/flex layout + no post-render text/order gate|V98|T57|one-column template + extraction validator + visual QA|
|B196|live official full-time row stores `['full_time']`|schema `employmentType` list cast to container string|V99|T57|scalar/list canonicalizer + live re-ingest|
|B197|tailored IT resume says troubleshooting occurred in municipal/county settings|resume validator checks vocabulary but not paid-setting attribution when professional IT experience is zero|V90,V100|T57|resume context-boundary + cover-title regressions; regenerate/visual QA|
|B198|regenerated cover implies paid Windows support, bridges unrelated settings, + collapses closing paragraph|anchor order/pronoun bridge/body structure unchecked|V100,V101|T57|zero-IT anchor/bridge + 3-body-paragraph gates; regenerate/visual QA|
|B199|full mypy rejects ATS coverage formatting|validator report typed as `dict[str,object]` instead of numeric field contract|V14,V98|T57|typed ATS report + rerun mypy/full gates|
|B200|live government jobs absent while official boards list them|generic cached CSS plans stale; CalCareers static target never submits search|V102,V105|T58|deterministic board adapters + live canaries|
|B201|verified-open legacy row remains hidden + cannot produce packet|archive stores timestamp only; official upsert never distinguishes dismissal from stale archive|V103|T58|typed archive reason + verified reopen regression|
|B202|current-market fallback omitted while query label can misclassify result market|global title filter + target-first market resolution cross policy boundaries|V104,V106|T58|result-location market overlay + market-specific title policy|
|B203|focused gate cannot import pytest|plain `python` resolves clean runtime venv intentionally lacking dev tools|V94|T58|invoke locked project `.venv` explicitly|
|B204|migration regression expects schema version 5|fixture hardcodes prior latest version after v6 addition|V51|T58|advance exact expectation + rerun migration gate|
|B205|live government adapter raises missing `url` argument|new parser tests used variadic fetch mocks that hid hardened fetcher client/headers contract|V102,V105|T58|real-signature mocks + bounded client calls + live rerun|
|B206|private search config rejects county match patterns|CalCareers emits county-only locations while strict policy requires state-qualified tokens|V31,V104|T58|normalize CalCareers county to `County, CA`; qualify config patterns|
|B207|correctional/probation officer rows pass destination office allowlist|include-title filter uses raw substring containment|V107|T58|boundary matcher + policy archive regression + local cleanup|
|B208|allowed current-market dispatcher/custodian marked score 1 before enrichment|detail stage embeds candidate-specific title rejection and mutates score state|V108|T58|remove title prefilter + stage-ownership regression + reset affected rows|
|B209|CalCareers rows cannot score; one apply URL becomes unrelated SafeLinks PDF|generic detail cascade lacks official DOM adapter and promotes arbitrary page links|V109|T58|official detail parser + exact application-entry regression + bounded DB repair|
|B210|valid score-5 government résumé has no cover after four drafts|model repeatedly shortens long parenthetical target title; exact-title gate has no deterministic repair|V101|T58|idempotent exact-title normalization + failed-stage rerun|
|B211|title-repaired cover still exhausts on unsupported `spring`|fabrication watchlist treats academic season/date as Spring software framework|V38,V110|T58|technical-context matcher + season/framework regression + failed-stage rerun|
|B212|full gate has 9 `no such column` fixture failures|hand-built unit schemas omit v6 availability/archive fields and bypass migrations|V51,V103|T58|advance minimal fixture schemas; keep production gates intact|
|B213|Roseville board shows 10 live jobs after async load; DivApply returns 0|agency landing placeholder treated authoritative; official fragment never fetched|V111|T59|fragment fetch + card dedup regression + live rediscovery|
|B214|version parity gate sees lock `0.5.5`|unqualified `uv` absent from PATH; lock update never ran|V14,V49|T59|invoke `.venv/Scripts/uv.exe`; rerun parity gate|
|B215|Database Analyst score says qualifications unavailable while stored text contains `&lt;...&gt;` degree rules|JSON-LD cleaner parses before decoding HTML entities|V112|T60|decode entities, strip markup, regression + rescore|
|B216|clean Database Analyst text has bachelor rule; score context retains only `click HERE` preamble|requirement window stops at the next heading but does not sample Experience/Training bodies|V113|T61|recognize bounded requirement subheadings + rescore|
|B217|live official manual URL remains source-closed|manual official upsert omits `availability_state=open`; reopen guard cannot fire|V97,V103|T62|persist verified-open state + source-closed regression|
|B218|generated résumés use only 64–71% page depth|fixed compact 9pt layout ignores sparse verified content|V98,V114|T62|content-neutral sparse typography + rendered visual/ATS QA|
|B219|strict Heart Cath tailoring exhausts on copied posting-only skill phrase|known unsupported skills trigger stochastic retries instead of safe deterministic removal|V90,V115|T62|prune unsupported skill items before validation; retain rejecting validator|
|B220|strict judge rejects exact authoritative `health communication coursework`|LLM absence verdict contradicts supplied exact candidate evidence|V44,V116|T62|narrow quoted-absence contradiction gate; context failures remain closed|
|B221|Heart Cath packet says municipal work was patient-facing + handled confidential records|healthcare guard enumerates 3 suffixes; confidentiality has no evidence gate|V38,V117|T62|generic patient-facing candidate regex + evidence-bound confidentiality guard; regenerate|
|B222|Device résumé calls municipal escalation `service desk-style`|paid EXPERIENCE lacks zero-professional-IT desk/ticket phrase gate|V100,V118|T62|exact source-evidence guard; regenerate|
|B223|0.5.9 preflight finds private locality in public docs + fixture|historical policy wording retained candidate market label|V48,V50|T63|market-neutral wording + focused/private/full release gates|
