# NEXUS STUDIO PRO — Release Readiness and Remaining Work

**Baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Inventory date:** 2026-11-19  
**Inventory source:** `docs/BUILD_STATUS.md`, `docs/OPERATOR_RUNBOOK.md`, `docs/HANDOVER.md`, `docs/PLATFORM_POLICY_MATRIX.md`, current Draft PR chain.

## Current checkpoint — 2026-11-19

- Core lane: PR [#323](https://github.com/justinhblee-prog/shorts/pull/323), Open / Draft / Unmerged. Latest docs-inclusive head `9bb930be024e42874f150ee46143213b04660c45`; GitHub Actions run [44496236632](https://github.com/justinhblee-prog/shorts/actions/runs/44496236632) passed `scripts/validate.sh` with **711 tests**.
- Latest Core engineering items: BUILD-00336 fair bounded TikTok retry ordering; BUILD-00337 due-candidate query-plan guard; BUILD-00338 indexed ordered scan with correlated latest-snapshot lookup; BUILD-00339 TikTok OAuth initialization and lease-fencing coverage; BUILD-00340 synthetic 10k-publication/10k-snapshot scan smoke test (712 tests, 0.50 ms CI measurement); BUILD-00341 Docker Compose integration smoke passed (all five services running, API readiness HTTP 200).
- UI lane: PR [#329](https://github.com/justinhblee-prog/shorts/pull/329), Open / Draft / Unmerged. UI-00001–00004 passed [run 44495954616](https://github.com/justinhblee-prog/shorts/actions/runs/44495954616) with **710 tests**. UI-00005 adds analytics refresh/busy state and displays the API's frozen `as_of` cutoff; exact-head validation is pending.
- Both lanes remain separate; the UI branch is based on the Core branch and the PRs remain unmerged.
- Browser rendering, actual CSV download, physical touch-device/screen-reader validation, real YouTube/TikTok OAuth and provider operations, Docker deployment, backup/restore drill, and actual cohort ROI remain unverified.
- Launch gate completion remains **1/8 (12.5%)**. Automated CI progress does not close any external/deployment gate.

## How progress is measured

Do not treat BUILD identifiers, open Draft PR count, or historical commits as a project completion percentage. They are not a finite acceptance denominator.

Track two separate measures:

1. **Launch gate completion:** the eight explicit pre-launch checks in the Operator Runbook. At this inventory checkpoint, 1 of 8 is verified by the current CI workflow (12.5% of launch gates); the other seven require environment, credential, operational, or business evidence.
2. **Engineering backlog:** rolling code and architecture audit. Its total is not yet finite because the repository does not define a complete release acceptance specification for every subsystem. Do not publish a fabricated overall percentage. Convert each newly discovered issue into a numbered BUILD item and update this inventory.

CI completion does not imply live provider, browser, platform, financial, or production readiness.

## Current checkpoint

- Latest completed engineering item in the current stacked chain: BUILD-00302 — serialize OAuth state and refresh-lease clocks after the SQLite write lock; CI passed on PR #308.
- PR #298 (BUILD-00292): https://github.com/justinhblee-prog/shorts/pull/298 — exact head `1f47019894854ea87565f00eb1c67fd64dbfbfeb`, GitHub Actions passed.
- PR #299 (BUILD-00293): https://github.com/justinhblee-prog/shorts/pull/299 — exact head `724d4f78425577debc74a7990cf4d34133162390`, GitHub Actions passed.
- PR #300 (BUILD-00294): https://github.com/justinhblee-prog/shorts/pull/300 — latest docs-inclusive head `00a55e1ae52a102a7eddfa52d3bc65c0b58aa8db`, GitHub Actions run #43990440580 passed.
- PR #301 (BUILD-00295): https://github.com/justinhblee-prog/shorts/pull/301 — exact head `62e5211c51305b71102c52f94b4525ca47b38407`, GitHub Actions run #43990907642 passed.
- PR #302 (BUILD-00296): https://github.com/justinhblee-prog/shorts/pull/302 — latest docs-inclusive head `22af5871853f7f124af9c92b37bf9887d3126a3a`, GitHub Actions run #43991125723 passed.
- PR #303 (BUILD-00297): https://github.com/justinhblee-prog/shorts/pull/303 — latest docs-inclusive head `5db4bd5ba8d307e9cd7c72aab5b3afd09dc1eedd`, GitHub Actions run #43991573385 passed.
- PR #304 (BUILD-00298): https://github.com/justinhblee-prog/shorts/pull/304 — latest docs-inclusive head `29759c56e2d05f8cf1226b55101dc612776214db`, GitHub Actions run #43992018437 passed (660 backend tests).
- PR #305 (BUILD-00299): https://github.com/justinhblee-prog/shorts/pull/305 — latest docs-inclusive head `705e897582d0592174719bc4bcff66051c4cc58d`, GitHub Actions run #43992365077 passed.
- PR #306 (BUILD-00300): https://github.com/justinhblee-prog/shorts/pull/306 — latest docs-inclusive head `d0e37b075d2efa46d0a0366642f75ce824238d7d`, GitHub Actions run #43992684188 passed (664 backend tests).
- PR #307 (BUILD-00301): https://github.com/justinhblee-prog/shorts/pull/307 — latest docs-inclusive head `001237c0cbb20b885557dec3ad2e1ec7c412cb58`, GitHub Actions run #43992985705 passed.
- PR #308 (BUILD-00302): https://github.com/justinhblee-prog/shorts/pull/308 — latest code head `2b70602d274a4ed583516a22d092728dee1a257d`, GitHub Actions run #43993556051 passed.
- PRs #298–#308 are open Draft PRs, stacked in dependency order, and remain unmerged. Earlier PRs #288–#295 and #297 remain Draft/unmerged; PR #296 is closed as a superseded duplicate. Preserve Draft status and do not merge or push to main.
- The scheduler regressions are deterministic SQLite lock-contention tests. They do not establish multi-host scheduler safety or deployed runtime readiness.

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

- [ ] Build and start Docker Compose on the deployment host; confirm API, worker and scheduler health. A separate CI Compose smoke workflow is being added under BUILD-00341 and does not count as deployment evidence.
- [ ] Exercise queue → worker → production record → review handoff → recovery on the deployed single-host SQLite volume.
- [ ] Verify scheduler pause, pending outbox replay, restart behavior and idempotency on the deployed host.
- [ ] Run a backup and restore drill against a copy of the persistent data volume.
- [ ] Verify dashboard workflows in a real browser, not only source-level DOM/syntax checks.

These checks supplement, rather than replace, the eight mandatory launch gates below.

## Phase 3 — Mandatory pre-launch gates

Source: `docs/OPERATOR_RUNBOOK.md`, section 8.

| # | Required evidence | Status |
|---:|---|---|
| 1 | `sh scripts/validate.sh` passes on Python 3.11+ | Verified in GitHub Actions for PR #293 head; CI only |
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
