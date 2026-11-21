# NEXUS STUDIO PRO — Engineering Handover

**Snapshot date:** 2026-11-21  
**Product baseline:** v0.1 (do not infer a production release from this engineering snapshot)  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Default branch:** `main`  
**Status:** Active development; all listed work remains Draft/open and unmerged.

## 1. Product objective

Operate a global short-form content business through one evidence-based workflow:

1. Discover topics and market signals.
2. Compare competitors and evaluate monetization scenarios.
3. Create scripts, voice and video through configured providers.
4. Review generated artifacts with a human approval gate.
5. Publish only through explicitly approved, private platform workflows.
6. Track measured platform performance and source-backed revenue/cost records.
7. Improve operations only when sufficient evidence exists.

Forecasts are estimates, not earnings. Missing source metrics must remain missing. AI generation, rendering, upload and monetization are distinct milestones.

## 2. Current development streams

### Storage, media and worker lifecycle

| PR | Scope | Latest known validation | Notes |
|---|---|---|---|
| [#452](https://github.com/justinhblee-prog/shorts/pull/452) | Incremental workspace upload quota reservation | Backend 919 tests; Compose integration passed | Atomic reservations during streamed uploads |
| [#453](https://github.com/justinhblee-prog/shorts/pull/453) | Pin reviewed FFmpeg/ffprobe binary digests | Backend 919 tests; Compose passed | Source-controlled manifest digests; not externally signed |
| [#454](https://github.com/justinhblee-prog/shorts/pull/454) | Fail closed on stale ClamAV signatures | 472 tests | Real signature refresh and malware scan still require deployment validation |
| [#456](https://github.com/justinhblee-prog/shorts/pull/456) | Installation-wide media cap and free-space preflight | Latest head `3dfcad2`: Backend 922 tests and Compose integration passed | Default global logical cap 20 GiB; default media free-space reserve 1 GiB |
| [#458](https://github.com/justinhblee-prog/shorts/pull/458) | Backup + restore workspace/target free-space guards | Head `2e29fdc`: CI run [44880391978](https://github.com/justinhblee-prog/shorts/actions/runs/44880391978) passed; 476 tests | Checks encrypted plaintext staging, bounded extraction estimate and final target copies; advisory, not physical reservation |
| [#459](https://github.com/justinhblee-prog/shorts/pull/459) | Scheduled cleanup of abandoned media staging parts | 467 tests | Scheduler lease holder; only old `.nexus-*.part` files |
| [#462](https://github.com/justinhblee-prog/shorts/pull/462) | Per-job worker scratch lifecycle | Latest code validation 472 tests; docs-only head follows | Private scratch, lease fencing, same-filesystem atomic media adoption, pre-claim free-space check |

Storage boundaries:
- Private media, worker scratch and backups are separate logical paths; Compose mounts media and worker scratch under `nexus_data`, while backups use `nexus_backups`.
- Worker scratch is isolated by job and lease identity. A stale worker must not remove a newer worker's files.
- Media upload checks, backup checks and worker scratch checks are best-effort free-space preflights. They are not hard volume quotas or kernel-level block reservations.
- Concurrent writers can consume free space after a check. Host/container quotas, capacity monitoring and alerting remain deployment responsibilities.
- The disposable Compose FFmpeg smoke disables only the media reserve inside that isolated test process; the normal 1 GiB default remains unchanged.

### Frontend and live API configuration

| PR | Scope | Validation |
|---|---|---|
| [#461](https://github.com/justinhblee-prog/shorts/pull/461) | Hosted frontend API origin and exact-origin CORS configuration | CI run 44870547319 passed; 468 tests |
| [#463](https://github.com/justinhblee-prog/shorts/pull/463) | Responsive PC/tablet/mobile preview with live API setup | Latest CI run 44877213798 passed; backend validation and Playwright browser smoke passed; fresh Vercel preview READY |
| [#466](https://github.com/justinhblee-prog/shorts/pull/466) | Loopback-only API port default and strict HTTPS CORS origin validation | Latest CI run 44878220058 passed; 470 backend tests and resolved Compose port assertion passed |
| [#460](https://github.com/justinhblee-prog/shorts/pull/460) | Earlier responsive preview shell | CI run 44870039465 passed |
| [#457](https://github.com/justinhblee-prog/shorts/pull/457) | Preview feedback helper newline-only change | Workflow requires action; not a functional prerequisite for #463 |

Current preview:
- [Responsive preview](https://nexus-studio-pro-ui-preview-hah79qazj-justinhblee-9540.vercel.app/preview.html)
- [Application root](https://nexus-studio-pro-ui-preview-hah79qazj-justinhblee-9540.vercel.app/)
- Vercel deployment: `dpl_4P4eeKVaZqhHEEU9Q1DoGd148V9y`, READY, commit `daaae441139103b90280a2dbc1f2993733d7f13f`.
- HTTP 200 verified for `/preview.html`, `/`, `/app.js`, `/styles.css` and `/cyber-magic.css`.
- Preview controls alter the actual iframe viewport (PC/tablet/mobile/auto, portrait/landscape, fit/100%); Auto mode fills the stage and tracks window resizing.
- Playwright browser smoke passed at PC 1440px, tablet 820px, mobile 390px, mobile landscape 844px, 1600px→1280px Auto resize, and 320px dashboard width with no horizontal overflow or uncaught page errors.
- CI screenshots are retained for 7 days in [run 44877213798 artifacts](https://github.com/justinhblee-prog/shorts/actions/runs/44877213798/artifacts/14696256756). This is headless browser validation, not physical-device testing.

Frontend API configuration:
- HTTPS backend origin can be set in the connection dialog (localhost is allowed for local development).
- Only the API origin is stored in localStorage. The review token remains in memory and is cleared on refresh.
- Backend CORS uses explicit `NEXUS_CORS_ORIGINS` origins, no wildcard and no credentialed CORS.
- A separately deployed backend and matching CORS configuration are still required for real live-data interaction.

### Multi-flow automation

- [#440 Windows multi-flow supervisor](https://github.com/justinhblee-prog/shorts/pull/440): detached Windows supervisor, three-worker concurrency and lifecycle tests.
- Git CLI automation CI passed; the actual Windows Claude CLI/provider session remains unverified because it requires the user's Windows environment and provider authentication.
- Do not claim unattended local Windows execution based only on hosted CI.

## 3. BUILD-00352 dependency-chain audit (2026-11-21)

The media/render work is not one flat set of independently mergeable PRs. The verified stack is:

```text
#436 lease-fenced render/artifact baseline
  └─ #444 integrated EDL submission + renderer/review
      └─ #448 verify render binary manifest at worker startup
          └─ #449 authenticated upload-to-render integration coverage
              └─ #450 workspace quota reservations
                  └─ #452 incremental upload-byte reservations
                      ├─ #453 reviewed FFmpeg/ffprobe digest lock
                      └─ #456 global media cap + physical free-space preflight
```

Important reconciliation finding:
- PR #444 currently reports `mergeable=false`. Its integration head `ba9c511` has 59 commits on top of ancestor `da945b4`, while the declared base branch now points at PR #436 head `23a55ed`, which is 19 commits ahead of that ancestor. Compare `da945b4...23a55ed` identifies seven base-side changed paths; five also changed in #444: `.devflow/tasks.json`, `.github/workflows/compose-smoke.yml`, `backend/queue_store.py`, `backend/tests/test_timeline_render_store.py`, and `backend/timeline_render_store.py`. This overlap is the concrete reconciliation area; do not change the PR base or overwrite either side blindly.
- The #444 branch is not merely behind: comparing current #436 head `23a55ed` to #444 head `ba9c511` shows 59 ahead / 19 behind. Keep #444 Draft/open/unmerged while preparing a reviewed integration of the five overlapping paths plus the three base-only paths (`backend/timeline_render_api_e2e_smoke.py`, `docs/BUILD_00352_RENDER_ARTIFACT_ADOPTION.md`, and related task/workflow changes).
- PR #452 is correctly based on the #450 workspace-quota branch; it is 4 commits ahead of that base with no behind commits. Its later descendants inherit the upstream #449→#448→#444 dependency.
- PR #458 now checks restore workspace capacity before encrypted decryption and before archive extraction, then checks final database/media target capacity; latest head `2e29fdc` passed 476 backend tests. PRs #458, #459 and #462 are separate main-based storage/worker improvements, but they do not replace the BUILD-00352 integration stack.
- A separate reconciliation candidate is open as Draft PR [#467](https://github.com/justinhblee-prog/shorts/pull/467), branch `reconcile/build-00352-pr444-on-436-2026-11-21`, latest head `1c0db8ef165a0558e08cab89c6a5e1e3dfd0c6a1` (documentation/task-ledger update). It is based on current #436 head `23a55ed` and preserves #444 head `ba9c511` as its second parent; it does not rewrite either source branch. Five overlapping paths were reconciled from their common ancestor, and the other #444-only files were carried forward. The Compose smoke workflow explicitly enables both `media-scan` and `render`; its authenticated HTTP E2E harness runs in the API container while the render worker remains network-isolated. API upload response normalization, exact EICAR signature, continuous video timeline and explicit audio track are covered. Code head `6b81e69` passed Backend [44882235365](https://github.com/justinhblee-prog/shorts/actions/runs/44882235365) with 914 tests and Playwright browser smoke; Compose [44882235333](https://github.com/justinhblee-prog/shorts/actions/runs/44882235333) passed full service readiness, ClamAV, render-worker isolation, real FFmpeg render/review, authenticated API upload-to-worker render/approval/private preview, and scheduled encrypted backup plus isolated restore. The task ledger now records this evidence and keeps target-host/provider validation open. Documentation-only latest-head reruns Backend [44882458891](https://github.com/justinhblee-prog/shorts/actions/runs/44882458891) and Compose [44882458904](https://github.com/justinhblee-prog/shorts/actions/runs/44882458904) both passed. PR #467 remains Draft/open/unmerged and mergeable; production/provider validation remains outstanding. Next code priorities are target-host media/lease validation when a target runtime is available, followed by production artifact retention/orphan cleanup and EDL overlap/duration semantics.

## 4. Validation evidence and limits

Latest relevant checks:
- #456 latest head `3dfcad292214649954fd645cff2c62f1cc5c5946`: Backend run [44874981857](https://github.com/justinhblee-prog/shorts/actions/runs/44874981857) success; Compose run [44874981840](https://github.com/justinhblee-prog/shorts/actions/runs/44874981840) success.
- #462 code head `6368c1d`: run [44874416537](https://github.com/justinhblee-prog/shorts/actions/runs/44874416537) success, 472 tests; subsequent docs-only head `c895df9` has run [44874507461](https://github.com/justinhblee-prog/shorts/actions/runs/44874507461) success.
- #463 responsive preview: latest run [44877213798](https://github.com/justinhblee-prog/shorts/actions/runs/44877213798) success; backend validation and responsive Playwright browser smoke both passed. Earlier baseline [44873045880](https://github.com/justinhblee-prog/shorts/actions/runs/44873045880) passed 468 tests.
- Preview deployment runtime log query returned no warning/error/fatal entries in the inspected 50-minute window; this is not proof of all browser paths working.

Automated CI and Compose smoke do not prove:
- Live AI script, TTS or render provider compatibility or output quality.
- Actual Windows Claude CLI operation under the user's credentials.
- Live YouTube/TikTok OAuth, account permissions, private upload processing or analytics coverage.
- Real financial reconciliation, monetization eligibility or positive net revenue.
- Host-level disk quotas, production monitoring, alerting or a disaster-recovery drill.
- Full manual visual review across physical devices and API-connected acceptance with a deployed backend.

## 5. External deployment prerequisites

1. Deploy the backend API to a supported HTTPS host; Compose now binds the published API port to loopback by default, so route remote browser traffic through a TLS reverse proxy.
2. Configure `NEXUS_CORS_ORIGINS` with the exact Vercel frontend HTTPS origin; the API now rejects wildcard/null/path/credential origins and non-HTTPS remote origins at startup. Preserve the loopback default unless a private ingress/firewall explicitly requires another bind interface.
3. Configure review/operator authentication and rotate all secrets outside source control.
4. Configure real script, voice and render provider endpoints and allowlisted renderer artifact hosts.
5. Configure YouTube/TikTok developer credentials and perform explicit account consent/verification.
6. Validate one controlled private upload and media playback before any larger batch.
7. Confirm backup encryption key custody, off-host backup replication, restore procedure and monitoring.
8. Run the full visual browser QA and API-connected acceptance flow with real test credentials.

## 5.1. Artifact reconciliation observability follow-up

- Draft PR [#468](https://github.com/justinhblee-prog/shorts/pull/468) is stacked on #467 via branch `feat/build-00352-artifact-reconcile-observability-2026-11-21`, latest code head `a4705b8`.
- The worker already ran orphaned staging and unindexed-file cleanup every 300 seconds with a 7200-second grace period. PR #468 adds success counters (files/directories/bytes) and failure-type logs, plus a service-level regression test.
- This is not indexed artifact retention/deletion, durable metrics/alerts or a hard storage quota. Target persistent filesystem validation remains required.
- Exact-head Backend [run `44882746096`](https://github.com/justinhblee-prog/shorts/actions/runs/44882746096) passed **915 tests** plus Playwright browser smoke; Compose [run `44882746102`](https://github.com/justinhblee-prog/shorts/actions/runs/44882746102) passed full FFmpeg/API/ClamAV/backup-restore integration and emitted `timeline_render_artifact_reconciliation_completed` with removal counters.

## 5.2. Render artifact storage capacity follow-up

- Draft PR [#469](https://github.com/justinhblee-prog/shorts/pull/469) is stacked on #468 via branch `feat/build-00352-render-artifact-cap-2026-11-21`, latest head `37b96da`.
- Adds a 20 GiB default installation-wide logical cap for indexed render artifacts, checked under the SQLite adoption write lock, and a 1 GiB default free-space reserve on the artifact filesystem.
- Zero reserve disables the free-space inspection; inability to inspect capacity fails closed when the reserve is enabled. Existing indexed artifacts are never automatically deleted.
- Adds regression tests for aggregate cross-workspace accounting, low/unavailable free space and the zero-reserve bypass.
- This logical cap is not an OS/container hard quota and excludes temporary staging/unindexed files. Retention/deletion and target-host quotas remain open.
- The temporary FFmpeg smoke helper uses its own `/tmp` artifact store and disables the production 1 GiB free-space reserve only for that disposable fixture store. The actual render worker receives both cap/reserve variables explicitly from Compose. Exact-head Backend [run `44883656236`](https://github.com/justinhblee-prog/shorts/actions/runs/44883656236) and Compose [run `44883656259`](https://github.com/justinhblee-prog/shorts/actions/runs/44883656259) passed.


## 5.3. EDL timeline duration, black gaps and explicit transitions

- Draft PR [#470](https://github.com/justinhblee-prog/shorts/pull/470) is stacked on #469 via branch `feat/build-00352-edl-gap-duration-2026-11-21`.
- Exact-head commit `e65d67f` passed Backend [run `44884162098`](https://github.com/justinhblee-prog/shorts/actions/runs/44884162098) and Compose [run `44884162025`](https://github.com/justinhblee-prog/shorts/actions/runs/44884162025): black initial/internal/trailing gaps and optional whole-millisecond project duration.
- The follow-up adds optional EDL v1 adjacent video crossfades (100–5000 ms), exact overlap matching and per-clip transition-duration bounds. FFmpeg uses deterministic `xfade=fade` offsets after normalizing clip streams. Existing audio-bed tracks remain independently positioned and muxed to the same project duration; embedded source-audio crossfades are not yet implemented.
- Latest crossfade code/test/real-media-smoke head: `f336a1c2019c8732d5f0e196d970174f0fa24039`. Backend [run `44884777926`](https://github.com/justinhblee-prog/shorts/actions/runs/44884777926) passed **925 tests**, Korean font fallback and Playwright browser smoke. Compose [run `44884777927`](https://github.com/justinhblee-prog/shorts/actions/runs/44884777927) passed service readiness, ClamAV, worker isolation, actual FFmpeg crossfade render, authenticated API E2E, review/private preview and encrypted backup/isolated restore. Both exact-head checks passed; the increment is CI-validated, not target-host/customer-media validated.
- Legacy EDL v1 payloads without the optional `transitions` field preserve their previous canonical snapshot digest. All work remains Draft/open/unmerged.


## 5.4. Embedded source-audio crossfade follow-up

- Draft PR [#471](https://github.com/justinhblee-prog/shorts/pull/471) is stacked on #470 via branch `feat/build-00352-source-audio-crossfade-2026-11-21`.
- Video clips can opt in to `include_source_audio`; the renderer reuses the same hash-verified staged asset, trims source audio to the clip source range and fails closed before encoding if the source has no audio stream.
- Video transition duration drives matching source-audio fade-out/fade-in intervals on the same absolute timeline. Source audio is mixed with explicit audio-bed tracks; combined track count is limited to eight.
- Exact latest branch head `8e4634e17b0940e25eadf5db953dc311702b5f56`: Backend [run `44885516326`](https://github.com/justinhblee-prog/shorts/actions/runs/44885516326) passed **928 tests** and Playwright browser smoke; Compose [run `44885516328`](https://github.com/justinhblee-prog/shorts/actions/runs/44885516328) passed real FFmpeg source-audio/video crossfade, worker isolation, authenticated API E2E, review/private preview and encrypted backup/isolated restore. Earlier functional head `4f216cb` also passed both CI workflows.
- Latest docs/task-ledger-only commits are being revalidated at the current branch head. This is generated-media CI evidence, not arbitrary customer-media or target-host validation. Embedded audio codec diversity and long-form media remain external test gates.

## 5.6. Read-only retention eligibility evaluator

- Draft PR [#473](https://github.com/justinhblee-prog/shorts/pull/473) is based on #471 branch head `8e4634e` and adds a pure evaluator only.
- It requires explicit versioned retention periods and grace periods, complete reference checks, zero active/snapshot references, explicit no-hold state, verified integrity, known storage state and known backup implications.
- It returns deterministic reason codes and UTC timestamps; it does not read/write a database, touch files, tombstone records or schedule deletion. Unknown inputs and malformed timestamps fail closed.
- Functional code head `50c7f204` passed Backend [run `44886115569`](https://github.com/justinhblee-prog/shorts/actions/runs/44886115569) (**939 tests plus Playwright browser smoke**) and Compose [run `44886115567`](https://github.com/justinhblee-prog/shorts/actions/runs/44886115567) (service isolation, real FFmpeg render/adoption/review, authenticated API E2E and encrypted backup/restore).
- Latest docs/task-ledger head `208f2e4aae1e697f71b434196108f94f8e3a4509` passed Backend [run `44886279762`](https://github.com/justinhblee-prog/shorts/actions/runs/44886279762) (**939 tests plus Playwright browser smoke**) and Compose [run `44886279825`](https://github.com/justinhblee-prog/shorts/actions/runs/44886279825) (service isolation, real FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore). PR #473 is CI-validated as a read-only evaluator only; no retention period or deletion behavior is enabled.
## 5.5. Artifact retention policy design

- Draft PR [#472](https://github.com/justinhblee-prog/shorts/pull/472) adds a non-destructive policy design stacked on #471.
- Current uploaded media `retention_until` defaults to 30 days but is metadata only; no asset expiry/purge worker exists. Backup archives default to 14-day pruning, independently of live media retention. Indexed render artifacts, EDL snapshots and review decisions are immutable and have no retention purge.
- The design specifies separate retention classes, unresolved owner/legal policy inputs, read-only eligibility evaluation, append-only tombstones/grace periods, lease-fenced binary purge and backup/replica coordination. No data deletion or retention period selection is included.


## 5.7. Workspace-scoped read-only retention inventory

- Draft PR [#474](https://github.com/justinhblee-prog/shorts/pull/474) is stacked on #473 via branch `feat/build-00352-retention-readonly-inventory-2026-11-21`.
- The inventory requires workspace membership, uses bounded workspace-filtered SELECT queries with SQLite `query_only`, and reports uploaded media, EDL snapshot asset references, job/review state and indexed artifact metadata without exposing storage paths.
- Malformed/truncated snapshots and unknown job state block reference checks. Cross-store reads are explicitly non-atomic; `reference_check_complete` always remains false.
- Legal-hold, file-integrity/storage and backup/replica state are unknown by design, so all candidates remain ineligible. No DB writes, filesystem access, queue mutation, leases, tombstones or deletion.
- Atomic read-snapshot code head `130dd2e9d9392880418e21aa3253defcfb466a92` passed Backend [run `44887197433`](https://github.com/justinhblee-prog/shorts/actions/runs/44887197433) (**944 tests plus Playwright browser smoke**) and Compose [run `44887197535`](https://github.com/justinhblee-prog/shorts/actions/runs/44887197535) (service isolation, real FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore).
- The inventory requires all stores to share one SQLite DB and performs the bounded SELECTs in one `query_only` read transaction. Malformed/truncated/unknown snapshot or job state still blocks reference completeness. Legal-hold, integrity/storage and backup/replica state remain unknown, so all candidates remain ineligible.
- Latest docs/task-ledger head `49d5e6c9ceeb3ed4baa58bed736277c50efd290c` is awaiting exact-head CI.


## 5.4. Retention inventory API follow-up

- Draft PR [#474](https://github.com/justinhblee-prog/shorts/pull/474) adds a workspace-scoped read-only inventory API: `GET /api/operator/workspaces/{workspace_id}/retention-inventory?limit=100`.
- The endpoint requires `operations.read` and authenticated workspace membership. It reads an explicit versioned policy from `NEXUS_RETENTION_POLICY_JSON`; missing policy blocks candidates and malformed JSON fails closed with a sanitized error.
- The inventory uses bounded workspace-filtered SELECT queries in a single SQLite `query_only` read transaction. It exposes safe metadata and reason codes only; no storage paths, keys, bytes or secrets.
- It never writes, tombstones, schedules cleanup or deletes. Legal hold, per-object integrity/storage and backup/replica state remain unknown and continue to block all candidates.
- Exact API head `4cdc96286cc6468760c8339c0ebe7dfc34aea47c` passed Backend [run 44887993545](https://github.com/justinhblee-prog/shorts/actions/runs/44887993545) (backend validation and Playwright browser smoke) and Compose [run 44887993469](https://github.com/justinhblee-prog/shorts/actions/runs/44887993469) (real FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore). This is generated-fixture CI evidence, not target-host or customer-media retention validation.


## 5.4. Retention inventory: per-object integrity evidence

- Draft PR [#474](https://github.com/justinhblee-prog/shorts/pull/474) latest head `741730c3787f449f950d98bd4b3142192021a18e`; exact-head Backend [run 44888403066](https://github.com/justinhblee-prog/shorts/actions/runs/44888403066) and Compose [run 44888403123](https://github.com/justinhblee-prog/shorts/actions/runs/44888403123) passed.
- The authenticated `GET /api/operator/workspaces/{workspace_id}/retention-inventory` requires `operations.read` and resolved workspace membership. Policy is supplied explicitly by `NEXUS_RETENTION_POLICY_JSON`; invalid configuration and storage errors fail closed.
- Original assets are verified using the existing workspace asset store's no-follow regular-file open and persisted byte-size/SHA-256 comparison. Render artifacts are verified through the immutable artifact store's root-confined lookup and checksum/size comparison.
- Integrity/storage evidence is a point-in-time filesystem observation after the atomic SQLite reference snapshot. Only status and evidence source are exposed; no path, storage key, raw digest or media bytes.
- Current backup code verifies archive-manifest database/media checksums during restore, but there is no per-object backup/replica registry. Legal-hold state also has no authoritative provider. Both remain unknown and block every eligibility decision. No files, backups or indexed artifacts were deleted.
- Latest inventory increment docs/task ledger head: `741730c`. Backend suite and Playwright smoke passed; Compose exercised service isolation, ClamAV readiness, FFmpeg render/adoption/review, authenticated upload/preview, encrypted backup and isolated restore.


## 5.5. BUILD-00353 offline provider contract increment

- Draft PR [#475](https://github.com/justinhblee-prog/shorts/pull/475), branch `test/build-00353-offline-provider-contracts-2026-11-21`, stacked on validated #474 head `741730c`.
- Audited current YouTube/TikTok OAuth and publishing adapters. Both OAuth implementations accept injected transports for deterministic offline testing; publishing suites use fake Google service objects and fake TikTok transports.
- Hardened Google and TikTok OAuth token adapters to reject non-object JSON responses. TikTok token expiry values must be positive, non-boolean JSON integers before tokens are encrypted/persisted.
- Added no-network regression tests for malformed response objects and invalid TikTok expiry values. Added matrix/runbook `docs/BUILD_00353_PROVIDER_OFFLINE_CONTRACTS.md`.
- Latest exact head `40dde147f8dc212be9d9a978a822abcf28d3234d` passed Backend [run 44888809207](https://github.com/justinhblee-prog/shorts/actions/runs/44888809207): 949 tests plus Playwright browser smoke, and Compose [run 44888809309](https://github.com/justinhblee-prog/shorts/actions/runs/44888809309): service isolation, ClamAV readiness, real FFmpeg render/adoption/review, authenticated upload/review/private preview and encrypted backup/isolated restore.
- BUILD-00353 remains externally blocked for live HTTPS contract checks, real script/voice/video generation, provider cost/latency evidence and publishing. Current OAuth stores are singleton/global; workspace-owned provider connections remain design-only in `WORKSPACE_PROVIDER_CONNECTION_CONTRACT.md`.
- No credentials, scopes, connected accounts, external uploads or public posts were changed. No live network calls were made.


## 5.6. Mainline CI incident and corrective Draft PR

- Current main HEAD is `c6749aff5761d19bfcc7cceae6b4950bc6cca7c4`. It contains a single test-only commit that added `backend/tests/test_artifact_retention_inventory_api.py` without its implementation module. The main Backend check [run 44887974099](https://github.com/justinhblee-prog/shorts/actions/runs/44887974099) failed during test discovery with `ModuleNotFoundError: artifact_retention_inventory`; 467 tests ran, one import error.
- This test-only commit was an accidental direct write to main caused by omitting the branch argument in a file-create operation. No other file was included in that main commit.
- Corrective Draft PR [#476](https://github.com/justinhblee-prog/shorts/pull/476) removes only the orphan test file through a separate branch and reviewable PR. Exact corrective head `86f27e79eecba46573cd0db568299cb508940c1b` passed Backend [run 44889142479](https://github.com/justinhblee-prog/shorts/actions/runs/44889142479): 466 tests.
- PR #476 remains Draft/open/unmerged. Main remains red until an authorized reviewer merges the correction or otherwise restores consistency; no merge, force push or history rewrite was performed.
- Current main branch protection is still disabled (`protected=false`, enforcement `off`); ruleset listing returns zero rulesets. This is an independent governance blocker. Do not make any further default-branch writes; all future file mutations must pass an explicit feature/docs branch argument.

## 6. Immediate next actions

1. Keep all Draft PRs open and unmerged; review corrective PR #476 before considering mainline CI restored. Preserve dependency ordering (#452 before #456/#453).
2. Reconcile #444 with the current #436 baseline, then revalidate the complete #444→#448→#449→#450→#452→#453/#456 stack at exact heads.
3. Revalidate the latest docs/task-ledger head for PR #471, then review PR #472's non-destructive retention design. Revalidate PR #474's latest docs/task-ledger head, then continue only read-only inventory observability. Keep all destructive retention operations blocked until owner/legal policy inputs and authoritative hold/storage/backup providers are approved.
4. Review the fresh Vercel preview manually on physical PC/tablet/mobile devices; headless Playwright coverage is now in place.
5. Deploy a non-production backend and verify exact-origin CORS plus authenticated frontend operations.
6. Validate real provider and platform workflows only after credentials and test accounts are available.
7. Refresh this handover whenever a major validation gate changes.

## 7. Safety and release rules

- No PR merge, production deployment or public publishing without explicit authorization.
- Public publishing remains gated by human approval; the implemented YouTube upload path is private-only.
- Never represent mocked provider tests as live AI generation.
- Never represent CI success as live platform connectivity or revenue success.
- Preserve existing UI and established workflows; keep independent modules separated and testable.


## 5.7. Retention inventory API and integrity evidence

- Draft PR [#474](https://github.com/justinhblee-prog/shorts/pull/474), branch `feat/build-00352-retention-readonly-inventory-2026-11-21`, exact code/integrity head `741730c3787f449f950d98bd4b3142192021a18e`.
- Workspace-scoped GET endpoint requires `operations.read` and resolved workspace membership. Explicit policy comes from `NEXUS_RETENTION_POLICY_JSON`; missing/malformed policy and storage failures fail closed with sanitized errors.
- Asset checks use no-follow regular-file opens and registered size/SHA-256; indexed render artifacts are verified through the existing artifact store. Filesystem checks are point-in-time observations after the consistent, bounded SQLite read snapshot.
- Exact-head Backend [44888403066](https://github.com/justinhblee-prog/shorts/actions/runs/44888403066) and Compose [44888403123](https://github.com/justinhblee-prog/shorts/actions/runs/44888403123) passed. Backend ran repository validation and Playwright browser smoke. Compose validated ClamAV readiness, worker isolation, generated-media FFmpeg render/adoption/review, authenticated upload-to-worker/private-preview E2E, encrypted backup and isolated restore.
- Latest documentation/task-ledger head is being revalidated separately. CI uses generated media and isolated storage; no customer-media, production-scale, target persistent-filesystem or legal compliance claim is implied.
- Legal-hold and per-object backup/replica evidence remain unknown; storage lifecycle state is not authoritative. All candidates remain blocked. No retention period, tombstone, purge or deletion is implemented.

## 5.8. BUILD-00353 offline OAuth contract increment

- Draft PR [#475](https://github.com/justinhblee-prog/shorts/pull/475), exact head `40dde147f8dc212be9d9a978a822abcf28d3234d`.
- YouTube and TikTok OAuth adapters reject non-object token JSON before persistence; TikTok expiry fields require positive non-boolean JSON integers. Deterministic fake-transport tests verify malformed payloads do not persist credentials.
- Exact-head Backend [44888809207](https://github.com/justinhblee-prog/shorts/actions/runs/44888809207) passed repository validation and Playwright browser smoke (**949 tests**); Compose [44888809309](https://github.com/justinhblee-prog/shorts/actions/runs/44888809309) passed the real-media render/API/backup integration suite.
- These are offline contract tests, not live Google/YouTube or TikTok HTTPS verification. Live provider validation remains blocked by operator credentials, an approved spend ceiling, licensing/data-processing review and authorized private test accounts. Existing token stores are global singleton connections; workspace-owned provider credentials remain a separate prerequisite before enabling independent B2B tenant connections.


## 5.9. Latest validation-note and provider contract follow-up

- PR #474 latest validation-note/task-ledger head `6b5ba0ee0da2ad103369f897804dadda10be9923`: Backend [44889771751](https://github.com/justinhblee-prog/shorts/actions/runs/44889771751) and Compose [44889771753](https://github.com/justinhblee-prog/shorts/actions/runs/44889771753) are running. Earlier code/integrity head `741730c3787f449f950d98bd4b3142192021a18e` and docs/task head `dd8a1a161db97729ca4c984bd5ce8d1cc2224f18` both passed their exact-head checks.
- PR #475 TikTok publishing response-hardening code/test head `ee5e563330d9e4e1956f24b3ba710fc19ebb048f` passed Backend [44889554706](https://github.com/justinhblee-prog/shorts/actions/runs/44889554706) and Compose [44889554618](https://github.com/justinhblee-prog/shorts/actions/runs/44889554618).
- PR #475 latest docs/task-ledger head `bff3af66e4adebb22839db616db943a01d404b49`: Backend [44889779907](https://github.com/justinhblee-prog/shorts/actions/runs/44889779907) and Compose [44889779960](https://github.com/justinhblee-prog/shorts/actions/runs/44889779960) are running.
- Both PRs remain Draft/open/unmerged. Live provider HTTPS/account validation remains externally gated; BUILD-00354 target-host deployment remains blocked.


## 5.10. Current exact-head status — 2026-11-21

- BUILD-00352 PR #474 remains Draft/open/unmerged at head `6b5ba0ee0da2ad103369f897804dadda10be9923`. Exact-head Backend [44889771751](https://github.com/justinhblee-prog/shorts/actions/runs/44889771751) and Compose [44889771753](https://github.com/justinhblee-prog/shorts/actions/runs/44889771753) both passed. The read-only inventory and per-object integrity checks are CI-validated; legal-hold and object-level backup/replica evidence remain unknown.
- BUILD-00353 PR #475 remains Draft/open/unmerged. YouTube/TikTok response-contract code/test head `b4934a69507d120a5cb484234d72c712d5671d3f` passed Backend [44890001360](https://github.com/justinhblee-prog/shorts/actions/runs/44890001360) (**954 tests**, font fallback and Playwright browser smoke) and Compose [44890002208](https://github.com/justinhblee-prog/shorts/actions/runs/44890002208) (ClamAV, worker isolation, generated-media FFmpeg render/adoption/review, authenticated API E2E, encrypted backup and isolated restore).
- PR #475 latest docs/task-ledger head `7575d24fd058b1a8b615e8ce4bee4268c77ee9cd` is under exact-head Backend [44890149253](https://github.com/justinhblee-prog/shorts/actions/runs/44890149253) and Compose [44890149269](https://github.com/justinhblee-prog/shorts/actions/runs/44890149269) validation.
- These checks use fake provider services and generated media. Live provider HTTPS/account checks, customer media, production-scale storage and target-host validation remain unverified. BUILD-00353 live gates and BUILD-00354 deployment authorization are still external blockers.
