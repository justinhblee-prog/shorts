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
