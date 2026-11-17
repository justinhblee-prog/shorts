# NEXUS STUDIO PRO — Release Readiness and Remaining Work

**Baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Inventory date:** 2026-11-17  
**Inventory source:** `docs/BUILD_STATUS.md`, `docs/OPERATOR_RUNBOOK.md`, `docs/HANDOVER.md`, `docs/PLATFORM_POLICY_MATRIX.md`, current Draft PR chain.

## How progress is measured

Do not treat BUILD identifiers, open Draft PR count, or historical commits as a project completion percentage. They are not a finite acceptance denominator.

Track two separate measures:

1. **Launch gate completion:** the eight explicit pre-launch checks in the Operator Runbook. At this inventory checkpoint, 1 of 8 is verified by the current CI workflow (12.5% of launch gates); the other seven require environment, credential, operational, or business evidence.
2. **Engineering backlog:** rolling code and architecture audit. Its total is not yet finite because the repository does not define a complete release acceptance specification for every subsystem. Do not publish a fabricated overall percentage. Convert each newly discovered issue into a numbered BUILD item and update this inventory.

CI completion does not imply live provider, browser, platform, financial, or production readiness.

## Current checkpoint

- Latest completed engineering item: BUILD-00291 — append-only queue and worker-control audit events.
- PR #297: https://github.com/justinhblee-prog/shorts/pull/297 (BUILD-00291 CI verified)
- Current PR #297 head: `3f0d4e534b16743c2b650b5f9ac2dc5e92fc678a`.
- GitHub Actions Backend tests run #43984822638 for that exact head: success.
- PRs #288–#295 and #297 remain Draft and unmerged; PR #296 is closed as a superseded duplicate. Preserve Draft status and do not merge or push to main.
- Completed next item: BUILD-00289 — capture enqueue transition timestamp after acquiring SQLite's immediate write lock and reuse it for the enqueue audit event. Its exact PR head passed GitHub Actions.\n- Active work item: BUILD-00290 — capture production-run creation time after acquiring SQLite's immediate write lock and reuse one timestamp for both created_at and updated_at.

## Phase 1 — Engineering closure (rolling)

**Exit criteria:** each code change has a focused regression, full CI validation on the exact PR head, updated BUILD ledger, and explicit limits on what was not tested.

Current ordered work:
1. BUILD-00289: enqueue job/event timestamp consistency under SQLite lock contention — CI passed on PR #294 head.\n2. BUILD-00290: production-run creation timestamp consistency under SQLite lock contention.
3. Audit every remaining queue, worker registry, scheduler/outbox, production-run, review, upload and reconciliation transition for timestamp sampling before lock acquisition or independently sampled audit times.
4. Audit transaction atomicity, idempotency, lease/generation fencing, ambiguous external outcomes, retry safety and immutable audit records across the same subsystems.
5. Reconcile API authorization and diagnostic redaction with UI actions; identify any shared-token/claimed-identity limitations before multi-user deployment.
6. Audit frontend workflows and accessibility/error/loading states; add browser-level checks where the deployment environment permits.
7. Re-run full repository validation after the audit queue is exhausted; fix all regressions and publish a verified test inventory.

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
