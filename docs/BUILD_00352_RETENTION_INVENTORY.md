# BUILD-00352 — Read-only retention inventory

**Status:** Read-only inventory/observability only; no deletion, tombstone, mutation or cleanup scheduling.

Module: `backend/artifact_retention_inventory.py`  
Entry point: `RetentionInventory.list_workspace(workspace_id, principal_id, policy, now=..., limit=100)`

## Scope and safeguards

- Requires workspace membership before querying data.
- Uses bounded, workspace-filtered SELECT queries and sets SQLite `PRAGMA query_only=ON` on each inventory connection.
- Reads original asset metadata, immutable EDL snapshot references, render artifact metadata, job states and review decisions.
- Does not read media bytes, expose storage paths/keys, verify file hashes, update rows, acquire leases, change queue state, create tombstones or delete files.
- Limits each asset/artifact class to 1–200 rows; snapshot reference scans are bounded to ten times the per-class limit. Truncation or malformed/unknown snapshot/job state marks the scan incomplete and blocks eligibility.
- Requires asset, artifact and snapshot stores to point to the same SQLite database, then reads all three record classes through one `query_only` read transaction. A mismatched database path fails closed.
- The reference scan is complete only when the bounded snapshot query is not truncated and every snapshot payload/job state is understood. Malformed or unknown records mark it incomplete.
- Returns per-candidate evaluator reason codes and aggregate blocker counts.

## Deliberately unknown state

The current schema has no legal-hold provider or per-object backup/replica inventory. This read-only layer also does not hash media files or stat storage paths. Therefore it supplies:

- `legal_hold: null`
- `integrity_verified: false`
- `storage_state_known: false`
- `backup_state_known: false`

These conditions deliberately block every candidate from `eligible_for_review`. A reference scan may be complete for the single read transaction, but this is not a purge authorization. Do not infer a no-hold state, verified media integrity or a backup guarantee.

The existing workspace asset `retention_until` value is returned as metadata only. Eligibility is calculated only from a caller-supplied explicit versioned policy; this module supplies no retention period.

## Output

The result includes workspace ID, bounded candidate count, eligible/blocked counts, blocker reason counts, truncation/reference-completeness flags, and candidates containing safe metadata plus the read-only evaluator result. No filesystem path or storage key is returned.

## Validation

Unit tests use an isolated SQLite fixture to verify workspace isolation, one-connection atomic reads, reference counts, active-job blockers, mismatched database fail-closed behavior, malformed snapshot handling, result truncation and unchanged row counts. Backend/Compose CI for the exact implementation head is required before this inventory is treated as validated. It does not prove production database scale, persistent filesystem behavior or customer-media retention compliance.


## Exact-head validation

Latest inventory head `cb09e67ba4a24c8c10e581d0da368d04ae7d1c33` passed Backend [run 44886936983](https://github.com/justinhblee-prog/shorts/actions/runs/44886936983) (**943 tests plus Playwright browser smoke**) and Compose [run 44886936974](https://github.com/justinhblee-prog/shorts/actions/runs/44886936974) (service isolation, real FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore). This validates generated SQLite fixtures and the broader Compose pipeline, not production database scale or retention compliance.


## Atomic read-snapshot validation

The atomic read-snapshot revision at head `130dd2e9d9392880418e21aa3253defcfb466a92` passed Backend [run 44887197433](https://github.com/justinhblee-prog/shorts/actions/runs/44887197433) (**944 tests plus Playwright browser smoke**) and Compose [run 44887197535](https://github.com/justinhblee-prog/shorts/actions/runs/44887197535) (service isolation, real FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore). The single read transaction makes reference counts internally consistent; unknown legal-hold, integrity/storage and backup state still blocks all candidates.
