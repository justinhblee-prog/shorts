# BUILD-00352 — Read-only retention eligibility evaluator

**Status:** Read-only implementation; no retention defaults, database integration, tombstones or deletion.

Module: `backend/artifact_retention.py`  
Entry point: `evaluate_retention_candidate(candidate, policy, now=...)`

## Policy input

The caller must provide an explicitly approved, versioned policy object:

Required fields (values must come from an approved organization policy; none are supplied by this module):

- `policy_version`: approved policy identifier.
- `retention_days.workspace_asset`: approved whole-day value.
- `retention_days.render_artifact`: approved whole-day value.
- `grace_days`: approved whole-day value.

- Retention periods must be whole integers from 1 to 3650 days.
- Grace period must be a whole integer from 0 to 3650 days.
- The policy version and a retention period for the candidate class are mandatory.
- No environment variable, code constant or database default supplies a retention period.

## Candidate evidence

Every candidate requires an ID, supported `data_class`, timezone-aware `created_at`, and explicit attestations:

- `reference_check_complete: true`
- `active_reference_count: 0`
- `snapshot_reference_count: 0`
- `legal_hold: false`
- `integrity_verified: true`
- `storage_state_known: true`
- `backup_state_known: true`

Workspace assets additionally require `asset_status: "active"` and scan status `"clean"` or `"rejected"`; pending/unknown scan state blocks eligibility. Render artifacts require a terminal review status: `approved`, `rejected` or `revision_requested`. EDL snapshots and review decisions are immutable provenance records and are not candidate classes.

The caller is responsible for gathering authoritative evidence. The evaluator does not query SQLite, infer reference counts, inspect storage, check backup replicas or decide legal holds.

## Result semantics

- `decision: "not_eligible"` with stable `reason_codes` when any required evidence is missing/unsafe or retention/grace has not elapsed.
- `decision: "eligible_for_review"` only means a separate, approved retention workflow may review the candidate.
- `expires_at` and `eligible_after` are returned as UTC ISO-8601 timestamps when computable.
- `destructive_action_performed` is always `false`.

This function does not create tombstones, acquire deletion leases, change rows, touch files, schedule cleanup or authorize deletion. A future purge implementation requires approved legal/product policy, append-only audit records, grace-period cancellation, final reference rechecks, lease fencing, path/hash verification and backup/replica coordination. Unknown state must remain ineligible.


## Exact-head validation

Latest evaluator head `50c7f2043cfa70a6cd27d7df9496c680148c2342` passed Backend [run 44886115569](https://github.com/justinhblee-prog/shorts/actions/runs/44886115569) (**939 tests plus Playwright browser smoke**) and Compose [run 44886115567](https://github.com/justinhblee-prog/shorts/actions/runs/44886115567) (service isolation, real FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore). These are generated-fixture CI checks, not a production retention rollout or target-host validation.
