# NEXUS STUDIO PRO — Release Readiness and Remaining Work

**Baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Inventory date:** 2026-11-19  
**Inventory source:** `docs/BUILD_STATUS.md`, `docs/OPERATOR_RUNBOOK.md`, `docs/HANDOVER.md`, `docs/PLATFORM_POLICY_MATRIX.md`, current Draft PR chain.

## How progress is measured

Do not treat BUILD identifiers, open Draft PR count, or historical commits as a project completion percentage. They are not a finite acceptance denominator.

Track two separate measures:

1. **Launch gate completion:** the eight explicit pre-launch checks in the Operator Runbook. At this inventory checkpoint, 1 of 8 is verified by the current CI workflow (12.5% of launch gates); the other seven require environment, credential, operational, or business evidence.
2. **Engineering backlog:** rolling code and architecture audit. Its total is not yet finite because the repository does not define a complete release acceptance specification for every subsystem. Do not publish a fabricated overall percentage. Convert each newly discovered issue into a numbered BUILD item and update this inventory.

CI completion does not imply live provider, browser, platform, financial, or production readiness.

## Current checkpoint

- Repository default branch remains `main`; current main head is `851b414262cc6bef8ec374ed0e7a25921521b295`. All development work below remains on Draft branches and is not integrated into main.
- PRs #311–#340 remain Open, Draft and unmerged. This includes the specifically protected PRs #311–#315. No merge or main push was performed.
- PRs #321–#328 (BUILD-00313 through BUILD-00320) have successful exact-head GitHub Actions checks. They form the development-control-plane chain for job orchestration, persistent runner state, verified Draft-PR completion, orphan recovery, bounded self-dispatch and Windows runner preflight.
- PR #329 is the separate UI workstream (UI-00001–00009). PR #330 is BUILD-00321, fixing paginated GitHub Actions intake; exact head `9195a6bddce5bef58f6ffd9bed17beb0be2b3818` passed run [44508180651](https://github.com/justinhblee-prog/shorts/actions/runs/44508180651).
- PR #337 adds BUILD-00358: Node 24-compatible actions for the Windows worker workflow, guarded by a pre-check that requires self-hosted runner version 2.327.1 or newer; exact-head backend Actions run [44512423036](https://github.com/justinhblee-prog/shorts/actions/runs/44512423036) passed 774 tests; the user's actual Windows runner version remains unverified.
- PR #338 adds BUILD-00359: strips backup-encryption, database, service-role and other credentials plus GitHub workflow command-file and runner-internal path variables from the local Aider subprocess; diagnostic redaction covers these secret classes. Exact head passed 775 backend tests.
- PR #339 adds BUILD-00360: immutable secret-file scope denylist for SSH/cloud/Kubernetes/Docker/GnuPG/Terraform/Pulumi/package-manager/service-account paths, with resolved-symlink target checks; exact head passed 776 backend tests.
- PR #340 adds BUILD-00361: isolates Aider's temporary HOME/USERPROFILE, XDG and Windows roaming/local app-data, Docker/npm/Git config; strips SSH/Git/package-manager/Aider/provider overrides, disables pip config loading and Git system/global/interactive credential behavior. Exact-head CI pending.
- PR #323 is the core/backend workstream BUILD-00315–00351. Exact core head `59ec8286f6c216345955593dd82a1047851fad4d` passed 725 backend tests and the five-service Compose/backup/restore smoke; this is synthetic CI evidence only.
- Parallel core follow-ups: PR #331 BUILD-00352 encrypted restore runbook passed 726 backend tests and Compose smoke; PR #332 BUILD-00353 upgraded CI actions to Node 24 and passed 726 backend tests plus Compose smoke; PR #333 BUILD-00354 strengthened retained-archive health and format validation, passing 729 backend tests plus Compose smoke.
- Stacked control-plane follow-ups: PR #334 BUILD-00355 global GitHub issue deduplication passed 768 backend tests; PR #335 BUILD-00356 bounded GitHub pagination passed 771; PR #336 BUILD-00357 repository path validation passed 773. These are hosted CI results on their exact Draft PR heads, not proof of a live token or self-hosted runner.
- The user reported Ollama installed and 64 GB RAM. This does not establish that the GitHub self-hosted runner is registered, online, running under the Ollama account, or able to access the local model.
- The default-branch schedules are not active until their reviewed workflows are integrated into `main`. No live local-model generation, real Draft-PR publication by the user's PC, or repeated LocalAppData persistence has been observed.
- The launch-gate score remains **1/8**. Hosted CI is the only verified mandatory gate; Compose deployment on the intended host, real AI/media providers, renderer playback, OAuth/private test upload, financial reconciliation, security/backup/restore operations, and ROI cohort evidence remain pending.

## Phase 1 — Engineering closure (rolling)

**Exit criteria:** each code change has a focused regression, full CI validation on the exact PR head, updated BUILD ledger, and explicit limits on what was not tested.

Current ordered work:
1. BUILD-00292: schedule activation timestamp after SQLite write-lock acquisition — CI passed on exact PR #298 head.
2. BUILD-00293: scheduler lease acquire/renew timestamps after SQLite write-lock acquisition — CI passed on exact PR #299 head.
3. BUILD-00294: due-dispatch timestamp and scheduler fencing lease validation in the reservation transaction — CI passed on PR #300.
4. BUILD-00295: dispatch-completion timestamp and fencing validation after queue acceptance — CI passed on PR #301.
5. BUILD-00296: schedule creation timestamp after SQLite write-lock acquisition — CI passed on PR #302.
6. BUILD-00297: failed-dispatch retry deadline and scheduler fencing validation after SQLite write-lock acquisition — CI passed on PR #303.
7. BUILD-00298: provider-attempt lifecycle timestamps and worker-lease fencing after SQLite write-lock acquisition — CI passed on PR #304.
8. BUILD-00299: YouTube metrics collector acquire/renew, collection-state and snapshot timestamps after SQLite write-lock acquisition — CI passed on PR #305.
9. BUILD-00300: TikTok publication transition, failure and audit timestamps after SQLite write-lock acquisition — CI passed on PR #306.
10. BUILD-00301: YouTube upload reservation, finalization, touch and reconciliation timestamps after SQLite write-lock acquisition — CI passed on PR #307.
11. BUILD-00302: OAuth state creation/consumption and TikTok refresh-lease timestamps after SQLite write-lock acquisition — CI passed on PR #308.
12. Continue the timestamp/atomicity audit across queue, worker registry, production-run, review, upload and reconciliation transitions.
13. Audit transaction atomicity, idempotency, lease/generation fencing, ambiguous external outcomes, retry safety and immutable audit records — rolling; BUILD-00303 and BUILD-00304 address append-only review evidence and late-completion retry safety.
14. Reconcile API authorization and diagnostic redaction with UI actions; identify shared-token/claimed-identity limitations before multi-user deployment.
15. Audit dashboard workflows, accessibility, loading/error states and add browser-level checks where a runnable browser environment is available.
16. Re-run full repository validation after the rolling audit queue is exhausted; fix regressions and publish a verified test inventory.

This is a rolling audit, not a claim that exactly six BUILD items remain. Add newly discovered defects in dependency order.

## Phase 2 — Integrated environment verification

**Exit criteria:** all three Compose services start and remain healthy; API, worker and scheduler exercise one complete supervised lifecycle; recovery and backup behavior are demonstrated.

- [ ] Build and start Docker Compose; confirm API, worker and scheduler health.
- [ ] Exercise queue → worker → production record → review handoff → recovery on the deployed single-host SQLite volume.
- [ ] Verify scheduler pause, pending outbox replay, restart behavior and idempotency on the deployed host.
- [ ] Run a backup and restore drill against a copy of the persistent data volume.
- [ ] Verify dashboard workflows in a real browser, not only source-level DOM/syntax checks.

These checks supplement, rather than replace, the eight mandatory launch gates below.

## Phase 3 — Mandatory pre-launch gates

Source: `docs/OPERATOR_RUNBOOK.md`, section 8.

| # | Required evidence | Status |
|---:|---|---|
| 1 | `sh scripts/validate.sh` passes on Python 3.11+ | Verified on exact Draft PR #336 head `771a81f1a14808a0793d3a52d1acf857e28655bc` (773 tests); hosted CI only |
| 2 | Docker Compose build/start; all three services healthy | Pending deployment evidence |
| 3 | Real script, voice and video generation; vendor compatibility, rights/licensing and costs checked | Pending real provider credentials and media review |
| 4 | Renderer CDN allowlist and staged MP4 playback verified | Pending real renderer artifact and playback |
| 5 | YouTube OAuth scopes and one private test upload on intended channel | Pending channel consent and credentials |
| 6 | YouTube Analytics and affiliate/sponsor statements reconciled against ledger | Pending real account and financial records |
| 7 | HTTPS, secret rotation, backups, restore drills, monitoring and alerting configured | Pending deployment/operations evidence |
| 8 | Small content cohort and actual net ROI validated before scaling | Pending actual cohort and cost/revenue data |

**Launch-gate score at this checkpoint: 1/8 (12.5%).** This is specifically the runbook launch checklist score, not the percentage completion of the entire product.

## Phase 4 — Scale and business proof

These are additional readiness constraints documented by the project, not completed launch gates:

- **Database and distributed execution:** current baseline is single-host SQLite. PostgreSQL migration, multi-host-safe worker/scheduler coordination, and distributed deployment are not verified. Do not scale multiple hosts against shared SQLite.
- **Identity and access:** current review workflow uses a shared operator secret and caller-asserted reviewer ID. A real identity provider, role-based authorization, and user-level audit attribution are required before multi-user production.
- **Platform policy:** preflight relies on human declarations; it does not inspect full media bytes, independently verify rights/consent, or guarantee policy approval. Verify actual platform disclosure capabilities and apply disclosure metadata where supported.
- **Real AI/media quality:** validate provider contracts, real generated outputs, licensing, render quality, artifact durability, and per-generation costs.
- **Financial/business validation:** reconcile actual income and costs; establish positive net ROI and stable cohort evidence before changing recommendation weights or scaling production.

## Reporting rules

- Report CI, deterministic SQLite tests, mocked provider tests, browser checks, live provider checks and production evidence as separate categories.
- A pending or queued workflow is not a pass. Match check-run SHA to the current PR head.
- Do not mark an item complete from source inspection alone when its exit criterion requires deployed or external evidence.
- Keep every PR Draft and unmerged; use a stacked branch chain. Never push directly to main.
- Update this file and `docs/BUILD_STATUS.md` when a gate changes state or a new material blocker is discovered.


### Engineering checkpoint — BUILD-00291
- Active work: append-only audit history for queue events and worker-control events.
- Required evidence: both audit tables reject UPDATE and DELETE with SQLite integrity errors while ordinary event appends continue to work.
- Limitation: privileged modification of the SQLite schema or database file remains outside this protection.


### BUILD-00291 — verified
- GitHub Actions Backend tests run #43984822638 passed on exact PR #297 head `3f0d4e534b16743c2b650b5f9ac2dc5e92fc678a`.
- `job_events` and `worker_control_events` reject UPDATE and DELETE through SQLite triggers.
- The protection does not prevent privileged schema or database-file modification and is not an external tamper-proof audit service.


### Engineering checkpoint — BUILD-00292
- Active work: scheduler schedule activation timestamp consistency under SQLite write-lock contention.
- Scope: `ScheduleStore.set_active` captures `updated_at` only after acquiring `BEGIN IMMEDIATE`; regression holds the database write lock and observes clock sampling.
- Validation pending for exact PR head; no deployed scheduler validation is claimed.


### Engineering checkpoint — BUILD-00293
- Active work: scheduler leader lease acquire/renew clock consistency under SQLite write-lock contention.
- Implicit timestamps are sampled after acquiring `BEGIN IMMEDIATE`; explicit `now` arguments remain authoritative.
- Required evidence: acquire and renew contention regressions pass on exact PR head.


### Engineering checkpoint — BUILD-00294
- Active work: scheduled dispatch reservation timestamp and fencing-lease consistency under SQLite write-lock contention.
- Clock sampling and lease validation now occur under the reservation write lock.
- Required evidence: exact-head CI including dispatch contention regression.



### BUILD-00303 — verified
- Add SQLite triggers that reject UPDATE and DELETE on `review_decisions` and `policy_evidence_events`; ordinary INSERT operations remain supported.
- Regression coverage verifies all four mutation/deletion attempts raise `sqlite3.IntegrityError` and both audit rows remain present.
- GitHub Actions run #43995020465 passed on implementation head `daa75c737b9d5b5b63b12b110dd65bdeb60ccfd0` (668 backend tests); exact docs-inclusive PR head validation is tracked separately.
- Limitation: SQLite triggers prevent accidental/application-level mutation, not privileged schema or database-file modification.


### BUILD-00304 — verified scope pending CI
- Retry reconciliation now refuses to authorize a retry if the authoritative production run is already `approved` or `uploaded`; queue and production-run transitions remain in the same SQLite transaction.
- Existing behavior for jobs whose production run has not yet been created is preserved.
- Regression covers a late upload completion discovered after an ambiguous cancellation and asserts no queue retry or reconciliation audit is committed.
- PR #309 (BUILD-00303): https://github.com/justinhblee-prog/shorts/pull/309 — exact head `ac96e68e4b661bcd638f0075d81732022720edd9`, GitHub Actions run #43995170924 passed (rerun attempt 2).
- PR #310 (BUILD-00304): implementation head `485f9d8e05e323323d38d73edf52e833b82c5f1b`, GitHub Actions run #44014933856 passed (669 backend tests). Docs-inclusive exact-head validation is pending.


### BUILD-00305 — worker generation identity
- Default worker IDs are now derived from the host name so a process restart on the same host rotates the existing registry generation and fences the prior process incarnation.
- Set `NEXUS_WORKER_ID` explicitly to a stable per-worker identity when the runtime hostname is ephemeral (for example, replaceable containers); do not use a random per-process value.
- Regression coverage: same-host restart identity stability, explicit override, and empty-host rejection.
- GitHub Actions runs #44015403212 and #44015410742 passed on implementation head `2a787581317cf4372f4dcf936ba56bec1079f199` (672 backend tests). This does not replace lease fencing or prove a distributed deployment's hostname/identity configuration. The documentation-inclusive checkpoint is being revalidated.


### BUILD-00306 — block resume while ambiguous provider outcomes remain
- `JobQueue.resume` now checks the full unresolved-ambiguous production-job count inside its write transaction and refuses to clear the global pause until every affected job has an audited reconciliation decision.
- A single reconciled job is insufficient when another ambiguous job remains. Retry authorization remains separate from resume; all provider outcomes must be investigated before the operator resumes production.
- Regression covers two concurrent ambiguous jobs, blocked intermediate resume, durable pause, and successful resume only after both reconciliations.
- Initial implementation head CI run #44016900395 passed (673 backend tests); the documentation-inclusive final PR head is validated separately. This does not independently validate operator-supplied provider evidence or a deployed production environment.


### BUILD-00307 — transcription provider attempt recovery
- Optional speech transcription now uses the durable provider-attempt journal, including request idempotency key, persisted response, adoption state, and ambiguous-outcome blocking.
- A recovered `response_received` transcription attempt is reused rather than sending a duplicate transcription request after restart.
- Tests cover successful journal adoption and crash recovery without a duplicate provider call.
- Provider-side idempotency behavior is not proven by local fixtures; verify the configured transcription service's key semantics and timeout/replay behavior in the deployed environment before production sign-off.


### BUILD-00308 — atomic provider response adoption
- Speech-alignment artifact persistence and provider-attempt adoption now share one SQLite write transaction and one worker-lease fencing decision.
- Regression tests cover successful paired commit and rollback of the artifact when the provider-attempt transition is invalid.
- This closes the local database crash window between the two writes. It does not make remote provider execution transactional and does not replace provider-side idempotency verification or deployed worker validation.
- Exact documentation-inclusive PR-head CI validation is pending.


### Engineering checkpoint — BUILD-00310
- Active work: accessible, scroll-aware Cyber Magic workspace navigation.
- The mobile sidebar now presents distinct compact icons for Dashboard, AI Content Studio, Content Planner & Intelligence, Approvals & Publishing, and Analytics & Operations; link names remain available to assistive technology.
- Active destination state follows scroll position, click navigation and URL hash, with `aria-current="page"`; keyboard focus and reduced-motion behavior are covered by frontend regression assertions.
- PR #316: https://github.com/justinhblee-prog/shorts/pull/316 — exact final-head CI is pending. No deployed browser or assistive-technology validation is claimed.
- This change does not close any mandatory launch gate. Keep the launch-gate score at 1/8 until environment and external evidence is supplied.


### Engineering checkpoint — BUILD-00311
- Extend atomic artifact/provider-attempt adoption to script, voice-generation and rendering; the previous split writes left a crash window after artifact commit but before attempt adoption.
- New regression checks paired adoption and rollback for all three stages.
- Validation pending exact PR-head CI. No live provider or deployed runtime validation is claimed; launch-gate score remains 1/8.


### Engineering checkpoint — BUILD-00312
- Free local inference is implemented as an optional self-hosted Windows runner workflow using Ollama; paid model APIs are not required.
- Gate: the workflow is not active from the default branch until reviewed and merged. The real runner/model execution has not been observed.

### Engineering checkpoint — BUILD-00313
- The development-job control-plane prototype is present on Draft PR #321: durable job DAG, dependency/lease lifecycle, scoped Aider execution, read-only GitHub intake, worker telemetry, and read-only dashboard.
- Exact PR-head hosted CI run [44075082662](https://github.com/justinhblee-prog/shorts/actions/runs/44075082662) succeeded.
- Gate: the local database must persist across runner cycles; Windows runner, real Ollama edit, token permissions, default-branch schedule and end-to-end PR publication remain unverified.

### BUILD-00314 — YouTube disclosure
- Exact PR #322 head passed hosted CI run [44076538828](https://github.com/justinhblee-prog/shorts/actions/runs/44076538828).
- Live OAuth/account access and real YouTube upload remain unverified.

### BUILD-00315 — TikTok disclosure
- Exact PR #323 head passed hosted CI run [44091928487](https://github.com/justinhblee-prog/shorts/actions/runs/44091928487).
- Tests use mocked transport; real TikTok OAuth/account access and public posting remain unverified.

### Engineering checkpoint — BUILD-00316
- Configure the development-job SQLite database under the Windows runner user's persistent LocalAppData directory, outside the checkout that GitHub Actions cleans between jobs.
- Add a workflow-contract regression for path selection and ordering.
- GitHub Actions run [44252322555](https://github.com/justinhblee-prog/shorts/actions/runs/44252322555) passed on code/test head `c05c7d5416b4b079a6366c849ec2e8a922921740` (741 backend tests plus frontend syntax check). The database is still local to one runner host/account and has no off-host backup; do not claim durable operation until the Windows runner has completed repeated cycles with the same database.
- Control-plane gate still open: `DevelopmentJobWorker` marks a job completed before the workflow's Draft-PR publication action runs, and no PR URL/head SHA is persisted as review evidence. Implement this gate before enabling autonomous scheduled execution.
- The launch-gate score remains 1/8. No production deployment, live provider validation, public publishing, or recovery drill is implied.


### BUILD-00317 — development-job review artifact gate (Draft PR #325)
- A validated code diff enters review_pending; it cannot unlock dependent work or count as completed until the exact Draft PR artifact is read back from GitHub.
- The verifier requires an open, unmerged Draft PR, the action's exact head SHA, the expected automation branch/default base, and inclusion of every recorded changed file. It uses GET-only API calls.
- Publication failure leaves the job visibly review_pending; exact-head hosted CI is pending. The change does not establish a Windows runner, real Ollama inference, or production deployment.


### BUILD-00320 — Windows local-runner readiness

- The development workflow now preflights Python 3.11+, Git Bash/POSIX sh, Node.js 18+, loopback Ollama API health, and the exact configured model tag before starting Aider.
- Backend requirements and Aider are installed in separate per-run workspace virtual environments; global/user Python packages are not modified by the workflow.
- The backend interpreter and Aider executable are selected explicitly to avoid PATH ambiguity between the two environments.
- This improves setup diagnostics and dependency isolation, but does not count as an integrated-environment launch gate. The owner-hosted Windows runner, real Ollama edit, repeated runner database persistence, Docker Compose deployment, and production backup/restore remain unverified.


### BUILD-00355 — idempotent GitHub issue intake
The read-only backlog sync now deduplicates by indexed `source_ref` across the complete development-job store, rather than the first 500 rows returned by the list API. The store enforces uniqueness for `github:issue:` source references under its SQLite write transaction, so concurrent intake runs cannot create duplicate issue jobs after racing preflight checks. Other seeded/documentation source references are unaffected. Exact-head CI is pending; no live Windows runner execution is claimed.


### BUILD-00355 — exact-head CI result
Exact head `743a10762fa57a49afee5d681d0899579ce93721` passed backend Actions run [44510490935](https://github.com/justinhblee-prog/shorts/actions/runs/44510490935) with 768 tests, including the beyond-500-row and transaction-race deduplication regressions. This is hosted CI only; Windows self-hosted runner and live Ollama execution remain unverified.


### BUILD-00356 — bounded GitHub API intake
Each GitHub backlog feed is now capped at five pages (500 records) per sync. Per-feed truncation metadata is returned with the snapshot and sync result, avoiding silent partial reads while preventing a routine cycle from scanning the repository's entire Actions history. Pagination links are restricted to the GitHub API host. Exact-head CI is pending; live token rate-limit behavior remains unverified.


### BUILD-00356 — exact-head CI result
Exact head `7c48c967eca8460378ffa9dc5ea13cacdfd89a16` passed backend Actions run [44511056511](https://github.com/justinhblee-prog/shorts/actions/runs/44511056511) with 771 tests, including the five-page cap, truncation propagation and rejection of non-GitHub pagination links. This is hosted CI only; live GitHub token rate-limit and Windows runner behavior remain unverified.


### BUILD-00357 — safe GitHub repository path construction
Owner and repository inputs are validated as individual path segments before any read-only GitHub API request. Invalid path traversal, embedded slashes, query/fragment syntax and whitespace fail before network access. Exact-head CI is pending; this is not live GitHub authentication evidence.


### BUILD-00357 — exact-head CI result
Exact head `b3de0e02310ccb353d07b6032dfa6620dd0b4a14` passed backend Actions run [44511457164](https://github.com/justinhblee-prog/shorts/actions/runs/44511457164) with 773 tests. Malformed repository path segments are rejected before API access while supported valid names remain accepted. Live GitHub authentication/rate-limit behavior remains unverified.


### BUILD-00358 — Windows runner Node 24 compatibility
The self-hosted development workflow now uses Node 24-compatible checkout v7 and create-pull-request v8. A PowerShell step runs before checkout and requires the active self-hosted runner to be version 2.327.1 or newer. Hosted CI can verify the workflow contract but cannot establish the user's actual Windows runner version; that remains a live-runner gate.


### BUILD-00359 — local model subprocess secret isolation
The constrained Aider executor now removes backup-encryption keys, database/Redis connection URLs, Supabase service-role credentials, service-account credentials and access/private/signing keys from the child environment, in addition to existing API/provider/GitHub secrets. GitHub workflow command-file variables, runner cache/results endpoints and runner temp/workspace/tool-cache paths are also withheld so the model cannot write outputs or inspect runner-internal files. Required local context (Ollama endpoint, workspace, approved scope mapping and model selection) remains available. Exact-head backend Actions run [44513202976](https://github.com/justinhblee-prog/shorts/actions/runs/44513202976) passed 775 tests; this is a local environment-filter contract, not a live model execution.


### BUILD-00360 — secret-file path denylist
The local Aider executor now rejects common SSH private identities, cloud credential folders, Kubernetes/Docker/GnuPG config, Terraform/Pulumi state, package-manager credential files, service-account JSON and private-key/keystore formats even when an issue scope mapping would otherwise include them. Credential-bearing subdirectories under `.config` are also blocked. The validator checks both the supplied path and its resolved symlink target. Exact-head backend Actions run [44513787916](https://github.com/justinhblee-prog/shorts/actions/runs/44513787916) passed 776 tests; no live runner filesystem scan is claimed.


### BUILD-00361 — isolated Aider home and tool configuration
Aider now runs with a per-job temporary user home and isolated XDG/Windows roaming and local app-data, Docker, npm and Git configuration paths; pip configuration-file loading is disabled with the platform null device. SSH/Git credential injection, inherited tool/provider endpoint overrides, and user package-manager configuration variables are removed. System/global Git config and interactive credential prompts are disabled, with an empty isolated global config and an explicit no-helper credential policy. OLLAMA_API_BASE is accepted only for loopback hosts; remote or invalid endpoints fall back to the local default. Exact-head CI pending; hosted tests do not establish real Windows runner or Ollama behavior.


### BUILD-00362 — subprocess runtime injection isolation
The local Aider executor removes inherited Python import/startup settings, dynamic-loader injection variables, shell startup hooks, and Node/Ruby/Perl preload settings before launching the model and validation commands. Regression coverage injects hostile values and verifies they do not reach the child environment. Exact-head CI pending; actual Windows runner and local model execution remain separate launch gates.


### BUILD-00363 — worker workspace isolation between job attempts
The bounded worker does not claim a second job after a failed or successful first attempt in the same workspace cycle. This prevents partial unvalidated edits from one Aider job contaminating the next job. Regression coverage verifies the second job remains ready after the first attempt fails with a partial edit. Exact-head CI pending; hosted tests do not establish Windows runner workspace cleanup.

### BUILD-00364 — exact file versus directory scope boundary
The Aider executor no longer infers recursive scope from a missing filename suffix. Existing directories are normalized with a trailing slash; ordinary file scopes are exact-match only. This prevents an extensionless file from being replaced by a directory tree that passes the scope check. Exact-head CI pending.


### BUILD-00365 — long-lived worker workspace safety
Long-lived worker/service loops no longer continue claiming jobs in a worktree after one job attempt. They remain idle-polling until work appears, then return after the attempt so the host can clean or replace the workspace. Tests confirm no second job is claimed. Exact-head CI pending.


### BUILD-00363–00365 — combined exact-head CI evidence
GitHub Actions run [44516995900](https://github.com/justinhblee-prog/shorts/actions/runs/44516995900) passed **782 backend tests**, repository validation and frontend JavaScript syntax validation for the combined worker, scope and daemon lifecycle changes. Hosted Linux does not prove Windows self-hosted runner or live local-model behavior.


### BUILD-00366 — exact file/directory semantics at the evidence gate
The durable store now applies the same explicit directory-marker rule as the Aider executor. Approved directory scopes are normalized against the trusted repository root before import; extensionless file scopes cannot authorize child paths. Exact-head CI pending.


### BUILD-00366 — durable scope gate CI evidence
GitHub Actions run [44517570254](https://github.com/justinhblee-prog/shorts/actions/runs/44517570254) passed **785 backend tests**, repository validation and frontend JavaScript syntax validation for the explicit directory-scope and durable evidence-gate changes. This is hosted Linux evidence only.


### BUILD-00367 — worker diagnostic secret containment
Retryable and non-retryable worker exceptions are passed through a shared redactor before persistence. The same helper sanitizes Aider subprocess output. Exact-head CI pending; this is a code-level redaction contract, not a production log inventory.


### BUILD-00367 — worker diagnostic redaction CI evidence
GitHub Actions run [44517983256](https://github.com/justinhblee-prog/shorts/actions/runs/44517983256) passed **786 backend tests**, repository validation and frontend JavaScript syntax validation for the shared diagnostic redactor and worker failure-persistence changes. This is a code-level contract, not a production log inventory.


### BUILD-00367 — multiline credential redaction evidence
GitHub Actions run [44518327365](https://github.com/justinhblee-prog/shorts/actions/runs/44518327365) passed **787 backend tests**, repository validation and frontend syntax validation, including multiline service-account JSON redaction. This remains a code-level test contract, not a production log inventory.


### BUILD-00367 — expanded worker evidence redaction
The shared redactor now handles PEM/OpenSSH private-key blocks, Basic authorization values, authenticated MongoDB/MySQL/AMQP URLs and common provider token formats. It sanitizes successful result summaries and validation references in addition to worker exceptions. Exact-head CI pending; no production log inventory is claimed.


### BUILD-00367 — credential-format validation evidence
GitHub Actions run [44518688714](https://github.com/justinhblee-prog/shorts/actions/runs/44518688714) passed **794 backend tests**, repository validation and frontend syntax validation, including quoted JSON credential keys, Basic auth, URL credentials, multiline PEM keys and provider token formats. This is not a production log inventory.


### BUILD-00367 — Actions log redaction evidence
GitHub Actions run [44518919606](https://github.com/justinhblee-prog/shorts/actions/runs/44518919606) passed **795 backend tests**, repository validation and frontend syntax validation, including a regression proving a token-bearing top-level workflow exception is redacted before stderr output. This is not a production log inventory.


### BUILD-00367 — final validation checkpoint
- Final PR head `d714efdccfbcec56503cc68c3e4fe9e7dcfc4790` passed backend Actions run [44519065531](https://github.com/justinhblee-prog/shorts/actions/runs/44519065531): **795 tests**, repository validation and frontend syntax check; includes top-level error redaction and approved-scope normalization.


### BUILD-00368 — stale worker process termination
An independent watchdog detects a lease deadline even while a heartbeat database call is blocked. Lease-loss signals are propagated to the Aider executor, which terminates the active command process tree. Hosted CI regression coverage is pending; Windows runner integration is still required to verify `taskkill /T /F` behavior. No live runner claim is made.


### BUILD-00368 — lease-loss fencing validation evidence
GitHub Actions run [44520050960](https://github.com/justinhblee-prog/shorts/actions/runs/44520050960) passed **797 backend tests**, repository validation and frontend JavaScript syntax validation. This includes the prolonged heartbeat failure and active POSIX process-tree termination regressions. Windows `taskkill /T /F` behavior is not validated by hosted Linux CI.


### BUILD-00368 — independent watchdog validation evidence
GitHub Actions run [44520547849](https://github.com/justinhblee-prog/shorts/actions/runs/44520547849) passed **797 backend tests**, repository validation and frontend syntax validation, including a deliberately blocked heartbeat call that exceeds the watchdog budget. Hosted Linux does not validate Windows `taskkill /T /F` behavior.


### BUILD-00369 — worker presence isolation
Worker presence records now use unique per-process session IDs so concurrent or retried processes on one host cannot overwrite one another's status. Hosted validation pending.


### BUILD-00369 — worker session identity validation evidence
GitHub Actions run [44521107433](https://github.com/justinhblee-prog/shorts/actions/runs/44521107433) passed **799 backend tests**, repository validation and frontend JavaScript syntax validation, including unique worker-session IDs across attempts and the 128-character bound.


### BUILD-00370 — command descendant termination
POSIX cancellation now escalates against the whole process group after SIGTERM, not only the group leader. A SIGTERM-resistant descendant regression is pending hosted validation. Windows `taskkill /T /F` remains an integration gate.


### BUILD-00370 — descendant termination validation evidence
GitHub Actions run [44521675405](https://github.com/justinhblee-prog/shorts/actions/runs/44521675405) passed **800 backend tests**, repository validation and frontend JavaScript syntax validation, including the SIGTERM-resistant orphan-descendant regression. Hosted Linux only; Windows `taskkill /T /F` remains an integration gate.


### BUILD-00371 — Windows path scope serialization
Case-insensitive scope overlap enforcement, separator/dot alias normalization and regression coverage are implemented. Exact-head hosted validation pending; hosted Linux cannot itself demonstrate Windows filesystem behavior.


### BUILD-00371 — normalized scope lock validation evidence
GitHub Actions run [44522472503](https://github.com/justinhblee-prog/shorts/actions/runs/44522472503) passed **801 backend tests**, repository validation and frontend JavaScript syntax validation, including Windows-style case and separator aliases on the scheduler contract. Actual Windows filesystem behavior remains a trusted-runner gate.


### BUILD-00372 — dependency mutation gate
Dependency additions after claim/finalization are rejected; pre-existing duplicate edges remain idempotent. Hosted validation pending.


### BUILD-00372 — dependency immutability validation evidence
GitHub Actions run [44522908956](https://github.com/justinhblee-prog/shorts/actions/runs/44522908956) passed **803 backend tests**, repository validation and frontend JavaScript syntax validation, including late-edge rejection and idempotent existing-edge coverage.
