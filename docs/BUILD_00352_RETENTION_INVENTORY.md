# BUILD-00352 — Read-only retention inventory

**Status:** Read-only inventory/observability only; no deletion, tombstone, mutation or cleanup scheduling.

Module: `backend/artifact_retention_inventory.py`  
Entry point: `RetentionInventory.list_workspace(workspace_id, principal_id, policy, now=..., limit=100)`

## Scope and safeguards

- Requires workspace membership before querying data.
- Uses bounded, workspace-filtered SELECT queries and sets SQLite `PRAGMA query_only=ON` on each inventory connection.
- Reads original asset metadata, immutable EDL snapshot references, render artifact metadata, job states and review decisions.
- Does not read or return media bytes, expose storage paths/keys or raw digests, update rows, acquire leases, change queue state, create tombstones or delete files. It does perform read-only per-object integrity checks through existing asset/artifact stores.
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

## Per-object integrity and storage observations

- Original assets use `WorkspaceAssetStore.verify_integrity`: it authorizes workspace membership, opens the private object without following symlinks, requires a regular file and compares byte size plus SHA-256 with registered metadata. The path and digest are not returned by the inventory endpoint.
- Render artifacts use `RenderArtifactStore.get`, which resolves the indexed object within the configured private artifact root and verifies its current SHA-256 and byte size against immutable index metadata. The endpoint reports only a verified/unverified status and evidence source.
- These filesystem observations run after the single SQLite read transaction. Reference counts and metadata are transaction-consistent; file integrity is a point-in-time observation and can change after the check. Any missing file, mismatch, permission error or provider exception remains unverified and blocks review eligibility.
- Aggregate `integrity_observations` counts verified and unverified candidates. No storage path, storage key, raw digest, media bytes or exception detail is exposed.
- The current backup subsystem creates an archive manifest containing media-file hashes and a database hash, and validates them during restore. It does not maintain an authoritative per-object backup/replica registry that can be joined to each candidate. Therefore `backup_state_known` remains false for every object and `backup_implications_unknown` continues to block eligibility.
- Legal-hold state also has no authoritative provider and remains unknown. No retention inventory action prunes backups or deletes assets/artifacts.

## Deliberately unknown state

The current schema has no legal-hold provider or per-object backup/replica inventory. The read-only layer verifies active source-asset and indexed render-artifact bytes against their registered size/hash using the existing storage adapters. Those observations happen after the SQLite reference snapshot and are point-in-time only. Missing, inaccessible or mismatched objects remain unverified. Therefore it supplies:

- `legal_hold: null`
- `integrity_verified: false` only when the corresponding object check is absent, failed or unavailable; successful per-object checks report verified evidence
- `storage_state_known: false` (there is no authoritative storage lifecycle/replica provider)
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

## Authenticated API and integrity provider validation

Draft PR #474 exact head `741730c3787f449f950d98bd4b3142192021a18e` passed Backend [run 44888403066](https://github.com/justinhblee-prog/shorts/actions/runs/44888403066) and Compose [run 44888403123](https://github.com/justinhblee-prog/shorts/actions/runs/44888403123). Backend CI completed `scripts/validate.sh`, Korean font fallback checks and Playwright browser smoke. Compose CI built the services, verified ClamAV readiness, worker isolation/resource limits, real FFmpeg EDL render and artifact adoption/review, authenticated API upload-to-worker/private-preview flow, plus encrypted backup and isolated restore.

The inventory endpoint requires `operations.read` and resolved workspace membership, reads explicit `NEXUS_RETENTION_POLICY_JSON`, and sanitizes malformed policy/storage errors. Asset integrity uses no-follow regular-file opens with size/SHA-256 comparison; render artifact integrity uses the existing indexed artifact store. Filesystem checks are point-in-time observations after the consistent SQLite metadata snapshot. The inventory does not establish legal-hold state, object-level backup/replica coverage, storage lifecycle state, production database scale, target persistent-filesystem behavior or customer-media compliance. Those unknowns continue to block all candidates from eligibility; no deletion or purge path exists.


## Documentation and task-ledger exact-head validation

The documentation/task-ledger follow-up at head `dd8a1a161db97729ca4c984bd5ce8d1cc2224f18` passed Backend [run 44889450213](https://github.com/justinhblee-prog/shorts/actions/runs/44889450213) and Compose [run 44889450217](https://github.com/justinhblee-prog/shorts/actions/runs/44889450217). Backend repository validation, font fallback and Playwright browser smoke passed. Compose service readiness, ClamAV, worker isolation, generated-media FFmpeg render/adoption/review, authenticated API upload-to-worker/private preview, encrypted backup and isolated restore passed. This validates the exact docs/ledger head; generated-media and isolated-storage limits remain unchanged.


## Latest exact-head validation

The latest feature plus documentation/task-ledger head before this validation-note update, `b99c3143c96aeaaa420acca03dec64e3ef86ac67`, passed Backend [run 44889623438](https://github.com/justinhblee-prog/shorts/actions/runs/44889623438) and Compose [run 44889623410](https://github.com/justinhblee-prog/shorts/actions/runs/44889623410). Backend repository validation, font fallback and Playwright browser smoke passed. Compose completed service readiness, ClamAV, worker isolation, real FFmpeg render/adoption/review, authenticated API upload-to-worker/private preview, encrypted backup and isolated restore. The current follow-up changes only this validation record and the task ledger; exact-head reruns are required.
