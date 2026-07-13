# DivApply critical-boundary remediation

## §G

- G1: eliminate Critical paths where untrusted job pages can drive host shell/files, inherit unrelated secrets, or cross-contaminate applicant artifacts.
- G2: keep automated applications functional inside least-privilege browser-only tooling; fail closed when CAPTCHA/email automation needs unavailable authority.
- G3: preserve baseline behavior outside named boundary changes; full configured test/lint/audit gates green.
- G4: bind every generated application artifact to one stable job identity; ⊥ wrong-job upload/delete.
- G5: preserve recoverability: transient provider failure remains retryable; backup captures active committed DB state.
- G6: bound network retry cost; make Windows/release/container paths reproducible + least privilege.
- G7: maximize truthful career-fit yield: IT support primary; health-IT/public-sector/education bridges; admin/banking fallback.

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
- R18: Roseville IT Technician I = entry level, little/no related work, hardware/software customer support + desktop/peripheral install/config; validates public-sector bridge. https://www.governmentjobs.com/careers/rosevilleca/classspecs/newprint/1512986
- R19: Playwright MCP `--init-page` can install context routes; built-in origin lists explicitly ≠ security boundary/redirect control. https://github.com/microsoft/playwright-mcp/blob/main/README.md

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
- V41: configured California-target jobs use the verified California application address consistently in forms and cover headers; other jobs retain base address.
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
|T29|retire contaminated distribution line + reserve clean `0.5.0`|version parity/retired-version test + PyPI/GitHub removal verification; V49|~|
|T30|add redacted tree/distribution private-value preflight|synthetic tree+wheel test + live private-profile scan; V50|x|
|T31|make launcher DB + symlink-retention regressions hermetic on Linux/Windows|focused launcher/maintenance tests + full OS matrix; V51,V52|x|
|T32|require tag release = current `main` tip|`test_v53_release_requires_exact_main_tip`; V53|x|
|T33|remove vulnerable JobSpy compatibility extra|secure-install contract + lock/audit checks; V54|x|
|T34|close residual JobSpy metadata/install drift|installer/CLI/lock/constraint + smoke checks; V55|x|

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
