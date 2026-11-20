# Tenant Data Isolation Audit and Migration Plan

**Date:** 2026-11-20  
**Status:** Inventory complete; first isolated media-staging primitive implemented; end-to-end workspace propagation and tenant data migration remain incomplete.

## Executive finding

The durable workspace registry and operator-management API are implemented and CI-verified. The application data plane is still largely global. A workspace membership check on the EDL validator does not make production jobs, artifacts, reviews, schedules, publishing accounts, analytics, or files tenant-isolated.

Do not market or enable this as complete B2B multi-tenancy until every resource below is partitioned and every API/worker path is workspace-aware.

## Current schema inventory

The following SQLite stores currently define tables without a `workspace_id` column:

| Area | Tables / resources | Risk if shared by customer workspaces |
|---|---|---|
| Queue and operations | `pipeline_jobs`, `job_events`, `production_reconciliation_events`, worker control/registry | Job enumeration, idempotency collisions, cross-tenant queue/event visibility |
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
- Cleanup must not be treated as tenant-safe until upload records themselves are workspace-scoped.

Tests added for same-job cross-workspace path separation, opaque directory names, invalid-ID rejection before network access, and cleanup isolation.

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
