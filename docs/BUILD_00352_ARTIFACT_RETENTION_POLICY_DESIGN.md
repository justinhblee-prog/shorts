# BUILD-00352 — Artifact and media retention policy design

**Status:** Non-destructive design only; no retention period selected and no indexed customer data is deleted by this document.  
**Snapshot:** 2026-11-21  
**Dependency:** Draft PR #471 (source-audio/video crossfade) on top of Draft PR #470 (EDL gaps, duration and video crossfade).

## 1. Current behavior verified in source

| Data class | Current behavior | Important limitation |
|---|---|---|
| Uploaded workspace media | `workspace_media_assets.retention_until` is assigned at registration; `register_stream` defaults to 30 days and accepts 1–3650 days. The row also has `status IN ('active','deleted')`. | The store currently has no expiry worker or purge method. `retention_until` is metadata, not an enforced deletion deadline. The deleted state is not a complete deletion workflow. |
| Indexed render artifacts | `render_artifacts` records are immutable; database triggers reject UPDATE and DELETE. Files are verified against SHA-256 on access. | No indexed-artifact retention/deletion policy exists. Do not remove files or mutate records outside a future reviewed design. |
| EDL snapshots and review decisions | Both tables have immutable UPDATE/DELETE triggers. Snapshots bind normalized EDL payloads and queue jobs; review decisions bind an artifact SHA-256. | They form an audit/provenance chain. Deleting source media or artifacts without an explicit archival/tombstone model can break replay, review and audit expectations. |
| Staging and orphan files | Old upload `.nexus-*.part` files and unindexed generated artifacts are cleaned by separate grace-period reconcilers. Render artifact reconciliation runs every 300 seconds with a 7200-second grace period. | This is crash cleanup only. It does not delete indexed artifacts, expired source assets or user-reviewed outputs. |
| Encrypted backups | Backup creation defaults to 14 days of backup retention and prunes old backup archives. | Backup retention is independent of media retention. A media file removed from the live volume can remain in existing backups until those archives and any off-host copies expire. |
| Capacity guards | Indexed render artifacts have a 20 GiB default logical cap and a 1 GiB default free-space reserve. | The logical cap is not a physical quota and does not authorize deleting old artifacts. Host/container quotas and monitoring remain external deployment work. |

## 2. Data lifecycle classes

Retention policy must be specified independently for each class; a single global timer is unsafe.

1. **Original uploads** — user-provided source images, audio and video, including quarantined, clean and rejected scan states.
2. **Generated render outputs** — private staged and indexed MP4/audio artifacts, including review-pending, approved, rejected and revision-requested results.
3. **Immutable provenance** — EDL snapshots, job records, review decisions, artifact checksums and audit events.
4. **Operational transient data** — partial uploads, per-job scratch directories, unindexed crash leftovers and temporary restore staging.
5. **Backup copies** — encrypted local archives and any separately configured off-host replicas.

The transient-data cleanup rules must remain distinct from customer-content retention. An orphaned unindexed file is not the same thing as an indexed user artifact.

## 3. Required policy inputs (unresolved)

No destructive retention behavior should be implemented until the owner/legal policy is approved for:

- Retention period and start event for original uploads (upload time, last use, workspace closure or explicit deletion request).
- Separate retention periods for review-pending, approved, rejected and revision-requested outputs.
- Whether users can export/download before expiry and how long that export window lasts.
- Whether approved outputs must remain available for publishing, analytics, dispute resolution or customer re-download.
- Legal hold, investigation, chargeback, licensing dispute and account-closure exceptions.
- Jurisdiction, customer contract, copyright/licensing terms and privacy/data-processing obligations.
- Whether retention is configurable by workspace, account tier or organization policy.
- How backups, replicas and disaster-recovery copies inherit deletion requests and legal holds.
- Audit metadata that must remain after binary deletion, and the user-visible behavior of an expired artifact link.

Do not invent a retention period or infer legal requirements from the current 30-day asset metadata or 14-day backup pruning defaults.

## 4. Proposed safe deletion architecture (design only)

### Phase A — Read-only eligibility evaluation

- Build a read-only evaluator that emits candidate IDs, data class, calculated expiry, reference blockers, hold blockers, backup implications and a reason code.
- Treat missing/invalid timestamps, unknown references, unknown policy versions and unavailable storage inventory as **not eligible**.
- Exclude assets referenced by non-terminal render jobs, retryable queue rows, review-pending work or any active export/publishing operation.
- Keep approved/rejected review outputs under their own policy; do not assume rejection means immediate deletion.
- Exclude any workspace, asset, snapshot or artifact under a legal/administrative hold.

### Phase B — Append-only tombstone and grace period

- Record a policy version, eligibility evaluation, actor/reason, requested time, scheduled purge time and hold status in a separate append-only retention ledger.
- Preserve immutable EDL snapshots, review decisions, checksums and audit history unless a separately approved legal policy says otherwise.
- For immutable `render_artifacts`, do not remove the existing immutability triggers. Model binary availability in a sidecar lifecycle/tombstone table rather than rewriting provenance rows.
- Use a grace period with cancellation/reversal before binary removal; repeated requests must be idempotent.
- Keep a durable audit event for every eligibility, hold, tombstone, cancellation, purge and failure transition.

### Phase C — Fenced binary purge

- Acquire a lease and re-check eligibility, holds, job state, artifact identity, expected storage key, root containment, symlink status, file type, byte size and SHA-256 immediately before unlink.
- Serialize the final reference check and tombstone state transition against new jobs/references.
- Remove only the exact generated storage key under the trusted root; never accept caller-provided paths.
- Verify that the binary is absent, record bytes reclaimed and emit a structured completion/failure event.
- Keep metadata/tombstone records so old IDs resolve to an explicit expired/deleted state rather than an ambiguous 404 or integrity error.

### Phase D — Backup and replica coordination

- A live-volume purge does not erase backup copies. Expose backup retention and replica propagation as part of the deletion status.
- Do not mutate or rewrite encrypted backups in place.
- Confirm that at least one required recovery copy remains available for the approved recovery window, unless the approved privacy/legal policy requires a different outcome.
- Document the maximum period during which deleted media may remain in local/off-host backups.

## 5. Required tests before any destructive rollout

- Asset still referenced by a queued, leased, retryable or review-pending job is never eligible.
- Active legal hold always blocks tombstone and purge; hold release requires an audited event.
- New references racing an eligibility check cannot slip past the final write-lock/lease fence.
- Expiry evaluation is deterministic across UTC/time-zone boundaries and policy-version changes.
- Invalid timestamps, missing DB rows, corrupted hashes, symlinks, path traversal and unavailable storage fail closed.
- Repeated tombstone/purge attempts are idempotent; a cancelled grace-period request does not delete the binary.
- A purge does not cascade-delete immutable EDL snapshots, review decisions or audit records.
- Backup/restore tests show the documented behavior for content already purged from the live store but still present in encrypted backups.
- Capacity accounting remains consistent after tombstoning, binary removal and reconciliation.
- Metrics include eligible count, blocked count by reason, tombstoned bytes, purged bytes, failures and oldest pending deletion.

## 6. Current implementation guardrails

- Keep the existing 5-minute/2-hour orphan reconciliation limited to unindexed crash leftovers.
- Keep the separate abandoned upload-part cleanup limited to generated partial files past its grace period.
- Do not change the current 20 GiB indexed artifact cap or 1 GiB free-space reserve as part of retention design.
- Do not delete or mutate indexed render artifacts, original media, EDL snapshots or review decisions in this task.
- Production hard quotas, persistent-filesystem crash/lease tests, alert delivery and backup replication remain target-host gates.

## 7. Next engineering step

Implement the read-only eligibility evaluator and tests only after the owner approves policy inputs. Until then, keep this document as a decision record and continue non-destructive storage observability work.
