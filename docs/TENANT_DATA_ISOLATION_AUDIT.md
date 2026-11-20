# Tenant Data Isolation Audit and Migration Plan

**Date:** 2026-11-20  
**Status:** Inventory complete; media staging is workspace-capable and the durable queue now stores nullable workspace ownership; API-to-worker authoritative propagation and tenant data migration remain incomplete.

## Executive finding

The durable workspace registry and operator-management API are implemented and CI-verified. The application data plane is still largely global. A workspace membership check on the EDL validator does not make production jobs, artifacts, reviews, schedules, publishing accounts, analytics, or files tenant-isolated.

Do not market or enable this as complete B2B multi-tenancy until every resource below is partitioned and every API/worker path is workspace-aware.

## Current schema inventory

The following SQLite stores currently define tables without a `workspace_id` column:

| Area | Tables / resources | Risk if shared by customer workspaces |
|---|---|---|
| Queue and operations | `pipeline_jobs` has nullable `workspace_id` and supports workspace-filtered claim/get/events primitives; `production_runs` inherits nullable workspace ownership from its queue parent; `job_events`, `production_reconciliation_events`, worker control/registry remain globally keyed | Legacy/unassigned jobs remain global; event/reconciliation queries and worker operations still need workspace scoping |
| Production | `production_runs`, `production_artifacts`, `provider_execution_attempts`, provider reconciliation events | Script/render artifact and provider-attempt exposure |
| Review and policy | `review_decisions`, `policy_evidence_events` | Customer review notes, approvals and rights declarations mixed |
| Brand configuration | `brand_profiles` | Brand profiles and editorial rules shared globally |
| Scheduling | `production_schedules`, `schedule_dispatch_outbox` | Customer schedule edits/dispatch can cross tenant boundaries |
| YouTube | `youtube_uploads`, video snapshots/events, OAuth states/tokens, collector state | Channel credentials and publication/analytics data need tenant ownership |
| TikTok | `tiktok_publications`, publication events, OAuth states/tokens, refresh lease | Account tokens and publishing state need tenant ownership |
| Finance and intelligence | `financial_ledger`, `trend_signals` and competitor/recommendation stores | Financial records and customer research may be exposed across tenants |
| Files | `MediaStager` filesystem paths derived from job IDs; no workspace asset registry yet | File ownership, retention, signed access and deletion are not tenant-aware |

The inventory is based on the current source schemas in `backend/queue_store.py`, `production_pipeline.py`, `review_workflow.py`, `brand_operations.py`, `scheduler_store.py`, `youtube_publishing.py`, `tiktok_publishing.py`, `youtube_oauth.py`, `tiktok_oauth.py`, `ledger.py`, `trends.py`, and `media_staging.py`.

## Implemented slice — workspace-scoped media staging

`backend/media_staging.py` now accepts an optional, validated `workspace_id` for `stage`, `staged_path`, and `cleanup_uploaded`. Tenant media is placed under a SHA-256-derived opaque workspace directory, with job filenames independently hashed. Temporary `.part` files are created inside the same namespace and pruning traverses nested namespaces. Invalid workspace IDs fail before the artifact download begins. Omitting `workspace_id` preserves the existing legacy path for current operator workflows.

This is a storage primitive only, not an end-to-end tenant boundary:
- Existing production recovery callers do not yet provide an authoritative workspace ID.
- Queue, upload-store lookups, worker leases, and production records are still not workspace-scoped.
- No tenant asset registry or authorized asset retrieval API exists.
- Legacy root-level files are not moved or assigned to a workspace.
- Workspace-scoped cleanup deliberately fails closed until upload records themselves support workspace-scoped reads; a global `get(job_id)` result is not sufficient ownership evidence.

Tests added for same-job cross-workspace path separation, opaque directory names, invalid-ID rejection before network access, and cleanup isolation.


## Implemented slice — durable queue workspace ownership

`backend/queue_store.py` now adds a nullable `workspace_id` column to `pipeline_jobs` using a non-destructive startup migration and indexes `(workspace_id, status, created_at)`. New enqueue calls may persist an explicit workspace ID, and the field is carried through the existing row decoder into claimed worker job objects. The global idempotency-key constraint is intentionally retained for compatibility; a key already associated with a different workspace fails closed with `IdempotencyConflict` rather than returning another workspace's job. Existing rows remain `NULL` and are not auto-assigned.

Tests cover persistence through claim, cross-workspace idempotency rejection, and invalid workspace values. This is schema/queue groundwork only:
- Current production and generic enqueue API routes do not yet derive workspace IDs from a verified customer identity.
- Claim selection is still global and worker execution/reconciliation is not yet tenant-filtered.
- Job events, production runs, artifacts and provider attempts do not yet have consistent workspace ownership.
- Global idempotency uniqueness is conservative but does not provide per-workspace idempotency; migration to a composite key requires a separately reviewed SQLite table rebuild and compatibility plan.


## Implemented slice — workspace-filtered queue and production parent ownership

- Production API create/read/provider-attempt endpoints accept an optional workspace selector header, but resolve it against the authenticated operator principal's configured/durable membership before use. Queue creation persists that resolved workspace; production and provider-journal reads apply SQL-level scope. Omitting the header preserves legacy global operator access and is not a customer-facing tenancy boundary.

- Queue claim can apply an explicit `workspace_id` predicate in SQL; queue `get` and `events` accept the same scope and return `JobNotFound` for mismatched ownership. Event reads derive workspace ownership through the immutable parent-job join rather than duplicating tenant data into audit rows. Heartbeat, finish and fail can additionally validate the claimed row's workspace before accepting a worker lease transition. The default unscoped behavior remains for legacy operator workflows and is not customer-safe authorization.
- Provider execution attempts and provider reconciliation audit rows now carry nullable `workspace_id`, backfilled from their `production_runs` parent. Insert triggers derive the value from the parent rather than accepting a caller-supplied tenant ID; workspace/state indexes support scoped operations. Legacy parent runs with NULL ownership remain NULL.
- ProductionStore adds nullable `production_runs.workspace_id` with a non-destructive migration and index. When a matching durable queue parent exists, creating a production run derives ownership from it and rejects non-production parents or conflicting existing ownership. Legacy standalone production records with no queue parent remain explicitly unassigned (`NULL`) for compatibility; they are not attributed to a tenant.
- Tests cover workspace-only claim selection, cross-workspace get/event denial, wrong-workspace lease transition rejection, invalid claim scope, production ownership inheritance and mismatch rejection.

Still outstanding: authenticated worker-to-workspace binding; customer identity is not yet integrated; only operator-authenticated workspace scoping is available; job event rows intentionally derive workspace ownership from the immutable parent job at read time; worker lease/heartbeat/finish/fail methods and provider attempt/reconciliation queries still rely on job ID and must be guarded by a trusted parent scope; existing production runs with NULL ownership remain unassigned. Do not pass request-supplied workspace IDs as proof of identity.

## Required migration sequence

### Phase 0 — identity contract

1. Select and approve the customer identity provider / OIDC contract.
2. Derive a stable principal from verified `issuer + subject`; never accept a principal ID from request JSON or an untrusted proxy header.
3. Keep operator/reviewer credentials separate from customer sessions.
4. Define invitations, owner transfer/recovery, account suspension, deletion, support access and audit retention.

### Phase 1 — schema expansion, no destructive rewrite

1. Add nullable `workspace_id` to tenant-owned parent records and related child records.
2. Add foreign keys/indexes and enforce parent-child workspace consistency in the same transaction.
3. Keep existing records unassigned during an audit; do not guess their customer owner.
4. Create a reserved operator/legacy workspace and only backfill records after an approved, evidence-backed ownership mapping.
5. Rework global uniqueness constraints such as queue idempotency keys to be workspace-scoped without weakening duplicate protection.
6. Preserve existing event/audit immutability and add workspace identity to each new event.

### Phase 2 — request/API enforcement

1. Resolve verified customer principal and active membership on every tenant API request.
2. Require a workspace context on all tenant-owned reads and writes.
3. Scope every SQL query by `workspace_id`; avoid fetching globally then filtering in application memory.
4. Bind workspace ID to the parent record when creating jobs, artifacts, reviews, schedules and financial entries.
5. Reject mismatched workspace IDs across referenced jobs, artifacts, assets and platform connections.
6. Add negative tests for cross-workspace list/get/update/delete, guessed IDs, replayed signed URLs, body/header spoofing and revoked members.

### Phase 3 — worker and media isolation

1. Carry immutable workspace ID from API submission through queue payload, lease, worker execution, provider attempts and results.
2. Re-check workspace ownership before every artifact adoption, review, publish, retry and reconciliation transition.
3. Store assets under server-generated workspace-scoped paths; never accept arbitrary local paths from clients.
4. Use opaque asset IDs, content fingerprints, bounded uploads, MIME/container inspection, malware scanning and short-lived signed access.
5. Add per-workspace quotas, retention/deletion workflows and backup/restore verification.

### Phase 4 — rollout gates

- Dry-run migration report reconciles every legacy record to exactly one owner or explicitly unassigned state.
- Backend integration tests prove no cross-tenant access through direct API, worker, scheduler, publishing and recovery paths.
- A two-workspace end-to-end test covers create → upload → produce → review → publish simulation → analytics.
- Production rollout is feature-flagged and reversible; do not drop old columns/tables until post-migration verification and backup retention windows expire.

## Current safe operating mode

- `NEXUS_WORKSPACE_AUTH_MODE=legacy_config` remains the default for EDL validation.
- `NEXUS_WORKSPACE_AUTH_MODE=sqlite` is an opt-in operator-only path; do not enable it in production before provisioning and verifying memberships.
- Workspace operator API is not customer account authentication.
- No workspace-scoped upload, asset read, production, publishing or analytics API is claimed complete.
- Existing data is not backfilled or modified by this audit.

## External decision required

The customer identity provider and account contract must be selected before implementing customer login or mapping external identities into workspace memberships. This is an external service/security contract and is intentionally not guessed or enabled by code.


## 2026-11-20 follow-up — exact-head CI and remaining operator execution gaps

- Exact head `7a749a6b20b3d858cb57085a2e1231db89d57e04`: Backend tests workflow run 44681380757 completed successfully, including `scripts/validate.sh`, Korean font fallback verification, and `scripts/ui_browser_smoke.mjs` (Chromium). Compose integration run 44681381054 also completed successfully. Browser screenshot artifact: 14605210220 (`nexus-dashboard-browser-screenshots`).
- Follow-up hardening now resolves the authenticated operator's workspace membership for `POST /api/production/jobs/{job_id}/execute` and `POST /api/production/jobs/{job_id}/adopt-recovered-render`. Both apply SQL-level parent/child scope; execution rejects a workspace-owned job when the selector is omitted, and recovered media staging uses the resolved workspace namespace. API tests cover missing, mismatched, and valid execution scope. This is still operator authorization, not independent worker identity authentication.
- Worker identity is still not independently authenticated/bound to an allow-list of workspaces. The request's `worker_id` and lease token are not a substitute for a trusted worker credential-to-workspace grant. Do not accept a workspace ID supplied by a worker as authorization. A trusted worker identity contract and per-workspace grant registry are prerequisites for customer-safe worker execution.
- Customer OIDC identity and full resource-family partitioning remain unimplemented. Existing unassigned (`NULL`) rows must remain unassigned pending evidence-backed migration.


### 2026-11-20 media lifecycle scope hardening

- Operator media staging now resolves authenticated workspace membership, reads the production parent with SQL workspace scope, and stages files only under the opaque workspace namespace. Missing workspace selection is denied for workspace-owned jobs.
- Staged media metadata and review-stage mutations now pass the resolved workspace into `ProductionStore.artifact` / `ProductionStore.stage`; both methods verify the parent production row's workspace inside the write transaction before changing child/parent state.
- Media cleanup now checks the parent production workspace first and passes the scope into `MediaStager.cleanup_uploaded`. Tenant cleanup intentionally remains fail-closed because the YouTube upload store is not yet workspace-scoped; no global upload lookup is treated as proof of tenant ownership.
- API and store tests cover missing/mismatched/valid media staging scope, fail-closed tenant cleanup, and SQL workspace fences for artifact/stage mutations.
- This does not complete worker identity binding, customer authentication, review/publishing/analytics family partitioning, or the full asset registry.


### Exact-head verification for media lifecycle changes

- Code/test head `f8170009c8f1b959039b21816273d468801a1b0e` passed Backend tests workflow run [44686718970](https://github.com/justinhblee-prog/shorts/actions/runs/44686718970), including `scripts/validate.sh`, Korean font fallback, and Chromium desktop/mobile browser smoke.
- Compose integration smoke passed [run 44686719048](https://github.com/justinhblee-prog/shorts/actions/runs/44686719048), including service build/start/readiness and scheduled backup + isolated restore.
- Fresh browser screenshot artifact: [14607235689](https://github.com/justinhblee-prog/shorts/actions/runs/44686718970/artifacts/14607235689) (5.37 MB).
- Subsequent commits `c186cef` and `e8c226e` are documentation-only worker identity contract/handover updates; no code changed after the verified code/test head.


### Tenant job read default-deny refinement — 2026-11-20

- Production detail, provider-attempt detail, queue job detail, and queue event endpoints now reject workspace-owned records when the operator omits the workspace selector. Previously, a missing selector could still reach a globally keyed read even though cross-workspace selectors were validated.
- Tests explicitly cover omitted workspace scope as well as valid and mismatched membership for production and queue reads.


## Review workflow workspace isolation — 2026-11-20

- Review pending/approved queues are filtered by the authenticated operator's resolved `X-Nexus-Workspace-Id`; omitted scope returns only legacy rows whose `workspace_id IS NULL`.
- Review approval, rejection, revision requests, and policy-evidence writes verify the production row and durable queue row against the same workspace inside the transaction. A mismatched or omitted scope for workspace-owned jobs is reported as not found.
- Review history and policy-evidence history validate the parent production row's workspace before returning events.
- Publishing overview and approved-review lists are derived only from the scoped approved-review query, preventing those list routes from enumerating other workspaces' job IDs.
- Regression tests cover cross-workspace review list isolation, decision denial, policy-evidence mutation denial, history denial, and successful same-workspace approval. Code head `7dc2b1742256832a744810188fdff1638668e6d7` passed Backend tests (run `44687938486`, including `scripts/validate.sh`, Korean font fallback, Chromium browser smoke, and artifact upload) and Compose integration smoke (run `44687938515`, including build, readiness, backup, and isolated restore).
- This remains operator-workspace isolation, not customer OIDC identity or full tenant isolation for publishing credentials, analytics, finance, trends, brand configuration, and other non-review domains.


## Scheduled production workspace ownership — 2026-11-20

- `production_schedules.workspace_id` is added with a nullable, non-destructive migration; existing schedules remain in the legacy NULL namespace.
- Schedule create/list/activation and outbox status/retry APIs resolve the authenticated operator's workspace membership and filter by the resolved workspace. Requests without a workspace selector see only legacy NULL-owned schedules.
- Scheduler dispatch reads the schedule's workspace ownership from its parent row and passes it to `JobQueue.enqueue`, preserving the same tenant boundary on generated production jobs. Outbox rows remain parent-owned; legacy orphan outbox rows are retained and exposed as unassigned legacy records rather than discarded.
- Regression coverage verifies workspace-scoped schedule listing/activation, dispatch ownership propagation, and outbox filtering; an existing migration test also verifies orphaned legacy outbox rows remain visible as unassigned records. Code head `effc7a497b9c64b2fbcef1b8d1b7bb3c004f5117` passed Backend tests + Chromium smoke (run `44688516667`) and Compose integration build/readiness/backup/restore (run `44688516822`).

## Publishing, analytics, finance, and opportunity workspace boundaries — 2026-11-20

- YouTube and TikTok publication job read/reconcile/execute routes now resolve the authenticated operator's workspace and verify the immutable production parent before accessing publication state. A tenant-owned job without a matching workspace selector is not returned; cross-workspace selectors are denied.
- YouTube video analytics refresh/read routes resolve the published video to its owning upload job, then verify that job's production workspace.
- YouTube and TikTok analytics history queries join snapshots back to the publication and production parent and filter by workspace. Standalone store-only test databases without the parent tables retain legacy unscoped compatibility only when no workspace is requested; a requested workspace receives no rows if the ownership chain is unavailable.
- Financial ledger rows now carry nullable workspace_id with a non-destructive migration. Job-linked entries must match the production parent's workspace; reports filter by workspace. Existing source-reference idempotency collisions across workspaces fail closed rather than returning another workspace's row.
- Scored opportunities now carry nullable workspace ownership; create/list APIs resolve membership and isolate records. Existing opportunities remain in the legacy NULL namespace.
- Shared brand profiles and externally collected public trend signals remain platform-level reference data, not customer-owned records. Their use to create production jobs propagates the selected workspace into the queue.
- Regression coverage added for publication parent access, video analytics access, financial ledger ownership, opportunity migration/isolation, and analytics-history parent joins. Latest combined Backend/Chromium and Compose validation for the current head is pending; do not mark these latest changes validated until both workflows finish successfully.

## Opt-in worker credential and lease boundary — 2026-11-20

- Added a SHA-256 digest-based worker credential verifier. A worker identity is bound to explicit workspace IDs; wildcard and empty grants are invalid. Presented bearer tokens are hashed and compared with constant-time digest comparison.
- Added opt-in worker v1 registration, production-job claim, heartbeat, completion, and failure endpoints. The worker identity is derived from the credential, never from a request body. The job's workspace is derived from the durable queue row and applied to every lease transition.
- Worker API claim is limited to short_video_production. A server-issued process-generation token is required for claims and all lease mutations; re-registration rotates it and stale generations are rejected.
- When NEXUS_WORKER_CREDENTIALS_JSON is configured, legacy operator-token worker claim/heartbeat/complete/fail endpoints return HTTP 410. The credential mode is disabled by default and no secret or runtime setting was added.
- Limitation: the current production worker still accesses SQLite directly and has not migrated to the new API. Direct database access bypasses HTTP credentials; this implementation is not a complete worker isolation boundary. OS/network sandbox, worker-runtime migration, append-only worker security audit, secret rotation procedure, and real remote worker execution remain pending.
- Authentication and API regression tests cover digest validation, explicit grants, workspace-fenced claim/lease transitions, legacy endpoint shutdown, and stale-generation rejection. Code head aa2fa5b96205323fa97e58e9fbda89c0a6199f68 passed Backend validation + Chromium browser smoke (run 44692285597) and Compose integration smoke (run 44692285539).

## Performance and recommendation evidence isolation — 2026-11-20

- Performance insights now filter YouTube and TikTok production/video snapshots by production_runs.workspace_id and financial aggregates by financial_ledger.workspace_id.
- Recommendation exposure snapshots persist workspace_id; deduplication is workspace-aware. Linking a selected recommendation to a production job verifies the production parent has the same workspace. Holdout evaluation reads only the selected workspace's exposure records.
- Trend recommendations and recommendation evaluation endpoints resolve the authenticated operator's workspace and pass that scope through performance evidence and exposure storage. Shared trend signals, public competitor observations, and brand profiles remain platform-level reference data.
- Dashboard toolbar now includes a responsive active-workspace selector populated from the authenticated operator's membership list. API requests include X-Nexus-Workspace-Id only when a workspace is selected; the unselected default remains the legacy NULL/unassigned namespace. The workspace list permission is a minimal workspace.read grant for supported operator roles.
- Browser smoke now seeds a test workspace and verifies that switching selection propagates the workspace header and returning to the default removes it. Latest CI for these changes is running; verify Backend/Chromium and Compose before marking validated.

- Deployment note: the durable workspace registry is selected with NEXUS_WORKSPACE_AUTH_MODE=sqlite. The default legacy_config mode requires an explicit NEXUS_OPERATOR_WORKSPACES_JSON mapping and does not silently fall back to the registry. No environment setting was changed by this code update.
