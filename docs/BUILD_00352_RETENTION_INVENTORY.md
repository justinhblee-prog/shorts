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

## Authenticated API

The inventory is exposed through `GET /api/operator/workspaces/{workspace_id}/retention-inventory?limit=100`.

- Requires the authenticated operator's `operations.read` permission and membership in the requested workspace; workspace scope is resolved before inventory reads.
- The optional `NEXUS_RETENTION_POLICY_JSON` environment variable supplies an explicit versioned policy. If absent, the empty policy deliberately yields blocked assessments; malformed JSON returns a sanitized service-unavailable response.
- The endpoint returns only bounded metadata, evaluator reason codes and aggregate counts. It does not expose filesystem paths, storage keys, media bytes, lease tokens or secrets.
- API errors do not disclose database paths or underlying exception details. The endpoint is GET-only and delegates to the same SQLite `query_only` read transaction.
- This endpoint does not authorize or perform a deletion. Even an eligible-for-review assessment is only an input to a separately approved future workflow.

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

## Authenticated API follow-up

Draft PR #474 adds the workspace-scoped GET endpoint and API authorization/configuration regression tests. Exact-head Backend and Compose CI are pending for the endpoint increment; prior inventory-only head `49d5e6c9ceeb3ed4baa58bed736277c50efd290c` passed Backend [run 44887364377](https://github.com/justinhblee-prog/shorts/actions/runs/44887364377) and Compose [run 44887364444](https://github.com/justinhblee-prog/shorts/actions/runs/44887364444). Do not claim the new endpoint validated until its own exact-head checks pass.
