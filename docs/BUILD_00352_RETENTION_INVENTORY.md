# BUILD-00352 — Read-only retention inventory

**Status:** Read-only inventory/observability only; no deletion, tombstone, mutation or cleanup scheduling.

Module: `backend/artifact_retention_inventory.py`  
Entry point: `RetentionInventory.list_workspace(workspace_id, principal_id, policy, now=..., limit=100)`

## Scope and safeguards

- Requires workspace membership before querying data.
- Uses bounded, workspace-filtered SELECT queries and sets SQLite `PRAGMA query_only=ON` on each inventory connection.
- Reads original asset metadata, immutable EDL snapshot references, render artifact metadata, job states and review decisions.
- Does not read media bytes, expose storage paths/keys, verify file hashes, update rows, acquire leases, change queue state, create tombstones or delete files.
- Limits each asset/artifact class to 1–200 rows; snapshot reference scans are bounded to ten times the per-class limit. Truncation or malformed/unknown snapshot/job state marks reference evidence incomplete and blocks eligibility.
- Returns per-candidate evaluator reason codes and aggregate blocker counts.

## Deliberately unknown state

The current schema has no legal-hold provider or per-object backup/replica inventory. This read-only layer also does not hash media files or stat storage paths. Therefore it supplies:

- `legal_hold: null`
- `integrity_verified: false`
- `storage_state_known: false`
- `backup_state_known: false`

These conditions deliberately block every candidate from `eligible_for_review`. This is not a defect or a temporary permissive mode; do not infer a no-hold state or a backup guarantee.

The existing workspace asset `retention_until` value is returned as metadata only. Eligibility is calculated only from a caller-supplied explicit versioned policy; this module supplies no retention period.

## Output

The result includes workspace ID, bounded candidate count, eligible/blocked counts, blocker reason counts, truncation/reference-completeness flags, and candidates containing safe metadata plus the read-only evaluator result. No filesystem path or storage key is returned.

## Validation

Unit tests use an isolated SQLite fixture to verify workspace isolation, reference counts, active-job blockers, malformed snapshot fail-closed behavior, result truncation and unchanged row counts. Backend/Compose CI for the exact implementation head is required before this inventory is treated as validated. It does not prove production database scale, persistent filesystem behavior or customer-media retention compliance.
