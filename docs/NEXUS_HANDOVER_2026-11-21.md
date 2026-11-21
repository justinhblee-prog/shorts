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
- Exact-head Backend run `44882746096` and Compose run `44882746102` are in progress.

## 6. Immediate next actions

1. Keep all Draft PRs open and unmerged; preserve dependency ordering (#452 before #456/#453).
2. Reconcile #444 with the current #436 baseline, then revalidate the complete #444→#448→#449→#450→#452→#453/#456 stack at exact heads.
3. Continue storage lifecycle integration checks across upload, render, scratch cleanup, backup and restore.
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
