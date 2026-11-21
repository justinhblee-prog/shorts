# NEXUS STUDIO PRO — Release Readiness

**Snapshot:** 2026-11-21 18:22 KST  
**Product baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Inspected default-branch HEAD:** `c6749aff5761d19bfcc7cceae6b4950bc6cca7c4`  
**Decision:** **NOT READY FOR PRODUCTION RELEASE**

This ledger separates source implementation and isolated automated checks from real provider, account, deployment, operational and commercial verification. A green CI job is not evidence that a live external service works.

## Critical repository-governance blocker

The GitHub branch endpoint for `main` reported `protected=false`; the protection object reported `enabled=false` and required status-check enforcement `off`. The repository ruleset endpoint returned zero rulesets. Consequently, GitHub currently has no observed server-side rule requiring pull requests or passing CI before changes reach `main`.

**Required operator action:** in repository Settings, create a ruleset or branch-protection rule targeting `main` that requires pull requests, at least one approval, required CI checks, and blocks force-push and branch deletion. Review administrator/bypass exceptions so automation cannot bypass the rule. Re-read the branch and ruleset APIs after saving. Until this is confirmed, do not trust unattended repository writes. This snapshot itself made no changes to repository settings.

## Evidence snapshot

| Area | Observed evidence | Release assessment |
|---|---|---|
| Default branch CI | Current main HEAD has one failed Backend check: run [44887974099](https://github.com/justinhblee-prog/shorts/actions/runs/44887974099), 467 tests ran and test discovery failed importing an orphan retention API test whose implementation module is not on main | **Failing; corrective Draft PR #476 opened** |
| PR discipline | #311–#315 and #318 individually confirmed open, Draft, unmerged; first two 100-item open-PR pages all Draft; `draft:false` search returned zero | Compliant in inspected results; pagination beyond page 2 not independently enumerated |
| Cyber Magic UI | #417 visual-system branch and #463 responsive preview; exact #463 head `daaae441139103b90280a2dbc1f2993733d7f13f` passed Backend + Playwright in [run 44877213798](https://github.com/justinhblee-prog/shorts/actions/runs/44877213798) | Partial; physical device visual acceptance and deployed browser-to-API session still required |
| Frontend-to-API | #461 adds configurable API origin and exact-origin CORS | Partial; deployed backend origin and live browser-to-API session not verified |
| AI/video pipeline | #420–#462 contain renderer, durable jobs, asset registry, upload quotas, lease fencing, scratch lifecycle and cleanup work | Partial; isolated CI/Compose is not a production workload or provider proof |
| Review gate | Source includes approval/review workflow and audit evidence | Live operator identity and deployed authorization not verified |
| Scheduling and publishing | Scheduling and platform adapters exist in source history | Real scheduled execution and public post on a user-authorized account not verified |
| OAuth/provider access | YouTube OAuth and Analytics code is present | Real consent, refresh, account scope and provider quota behavior not verified; TikTok live authorization not verified |
| Analytics | YouTube/TikTok collection and dashboard code/tests exist | Live account metrics and provider reconciliation not verified |
| Backup/recovery | Encrypted backup/restore code and isolated Compose checks exist in PR evidence | Real deployment restore, off-site copy, key custody and recovery-time test not verified |
| Security | Upload/path/lease/ClamAV checks are covered by automated tests | Live ClamAV signature refresh, malware scan, host/container quotas and branch protection not verified |
| Local Windows AI automation | User reports Ollama installed; 64 GB RAM | Runner registration, model invocation and GitHub-to-PC Draft-PR round trip not verified |
| Commercial readiness | Revenue/cost ledger and scenario forecasts exist | No verified real revenue, ROI or operating-cost history |

## Exact CI references checked

- PR #463 exact head `b3e1ef6ae1a6fbdc6851a5015c4be2520671ed65`: Backend tests passed in [run 44877045770](https://github.com/justinhblee-prog/shorts/actions/runs/44877045770) and [run 44877041841](https://github.com/justinhblee-prog/shorts/actions/runs/44877041841). No responsive-preview browser-smoke run was found for this exact head.
- PR #462 exact head `c895df98a96894eb097b26a50b59f15ba1388875`: Backend tests passed in [run 44874507461](https://github.com/justinhblee-prog/shorts/actions/runs/44874507461).
- Main HEAD `c6749aff5761d19bfcc7cceae6b4950bc6cca7c4`: one failed Backend check in [run `44887974099`](https://github.com/justinhblee-prog/shorts/actions/runs/44887974099). The failure is `ModuleNotFoundError: artifact_retention_inventory` while importing `backend/tests/test_artifact_retention_inventory_api.py`; 467 tests ran, with one import error.
- Corrective Draft PR [#476](https://github.com/justinhblee-prog/shorts/pull/476) removes only the orphan test file from mainline via a reviewable PR; no history rewrite or direct main write. It is pending CI and must not be merged without authorized review.
- BUILD-00352 retention inventory PR [#474](https://github.com/justinhblee-prog/shorts/pull/474) exact head `741730c3787f449f950d98bd4b3142192021a18e` passed Backend [44888403066](https://github.com/justinhblee-prog/shorts/actions/runs/44888403066) and Compose [44888403123](https://github.com/justinhblee-prog/shorts/actions/runs/44888403123).
- BUILD-00353 offline OAuth contract PR [#475](https://github.com/justinhblee-prog/shorts/pull/475) exact head `40dde147f8dc212be9d9a978a822abcf28d3234d` passed Backend [44888809207](https://github.com/justinhblee-prog/shorts/actions/runs/44888809207): 949 tests + Playwright, and Compose [44888809309](https://github.com/justinhblee-prog/shorts/actions/runs/44888809309).

## Release gates that must all be evidenced

1. Main branch protection and required CI/review rules are active and independently re-read.
2. Cyber Magic primary screens, navigation and responsive behavior pass browser visual/interaction QA against the approved reference.
3. Frontend API configuration is exercised against a deployed backend with correct CORS and authenticated requests.
4. AI generation and video rendering complete end-to-end with an authorized real provider, real media inputs and verified MP4/audio outputs.
5. Durable queue, worker leases, retries, cancellation, recovery and review approval are exercised under a deployed runtime.
6. Scheduling, OAuth, publishing and analytics are verified against explicitly authorized real SNS accounts; public publishing remains human-approved.
7. Encrypted backup and restore are tested against a disposable but production-equivalent deployment, with an independently stored recovery key and off-site backup copy.
8. Security controls, operational monitoring, resource limits, incident recovery and real cost/revenue evidence are reviewed before release.

## Next work order

1. Reviewer: inspect corrective Draft PR #476 and restore mainline test discovery; main remains red until a reviewed correction is merged. Operator: enable and verify branch protection/ruleset on `main` (required external action; not available through the current GitHub read/write tool surface).
2. Engineering: validate the integrated FFmpeg/render branch at its exact final head, including browser preview smoke and Compose artifact/review flow; do not infer completion from constituent PRs.
3. Engineering: verify Windows local Ollama runner registration and tool-call protocol without paid APIs, then confirm a single Draft PR round trip.
4. Operator: provide authorized deployment/provider/OAuth configuration only when a live-service validation window is explicitly approved.

No PR is merged and no history rewrite is performed. A test-only file was inadvertently committed to `main` in commit `c6749af`; corrective Draft PR #476 is open to remove that orphan file. Branch protection remains disabled. No local PC folder or production data is changed by this checkpoint.


## 2026-11-21 — current exact-head evidence refresh

- **Mainline remains NOT READY:** main HEAD remains `c6749aff5761d19bfcc7cceae6b4950bc6cca7c4`, and its Backend run [44887974099](https://github.com/justinhblee-prog/shorts/actions/runs/44887974099) failed test discovery due to the orphan retention-inventory API test. Do not write directly to main.
- Corrective PR [#476](https://github.com/justinhblee-prog/shorts/pull/476) remains Draft/open/unmerged at `86f27e79eecba46573cd0db568299cb508940c1b`; exact-head Backend [44889156318](https://github.com/justinhblee-prog/shorts/actions/runs/44889156318) passed **466 tests**. Main remains red until an authorized reviewer merges the correction.
- Branch protection is still disabled and no rulesets are observed. This requires repository administrator action; do not attempt to change settings from automation.
- Responsive UI PR [#463](https://github.com/justinhblee-prog/shorts/pull/463) head `daaae441139103b90280a2dbc1f2993733d7f13f` passed Playwright [44877213798](https://github.com/justinhblee-prog/shorts/actions/runs/44877213798). Vercel preview is READY at [NEXUS STUDIO PRO responsive preview](https://nexus-studio-pro-ui-preview-hah79qazj-justinhblee-9540.vercel.app/preview.html); HTTP 200 was verified for the preview, app entry and JS/CSS assets. Live API still requires a separately deployed/configured backend.
- API exposure PR [#466](https://github.com/justinhblee-prog/shorts/pull/466) head `97e92513295b7d6fac9e7a656535373ccdae6e59` passed Backend [44878220058](https://github.com/justinhblee-prog/shorts/actions/runs/44878220058), 470 tests and resolved Compose loopback-bind assertion.
- BUILD-00352 reconciliation PR [#467](https://github.com/justinhblee-prog/shorts/pull/467) head `a3c61e146c660c73eb74cd952d614de581a3e950` is 69 ahead / 0 behind and GitHub mergeable. Backend [44894519601](https://github.com/justinhblee-prog/shorts/actions/runs/44894519601) and Compose [44894519568](https://github.com/justinhblee-prog/shorts/actions/runs/44894519568) passed; profile-aware cleanup removed the ClamAV updater, test volumes and network without resource-in-use warnings.
- BUILD-00352 retention inventory PR [#474](https://github.com/justinhblee-prog/shorts/pull/474) exact head `6b5ba0ee0da2ad103369f897804dadda10be9923` passed Backend [44889771751](https://github.com/justinhblee-prog/shorts/actions/runs/44889771751) and Compose [44889771753](https://github.com/justinhblee-prog/shorts/actions/runs/44889771753). Inventory remains read-only; unknown legal hold/backup evidence blocks all candidates.
- BUILD-00353 provider PR [#475](https://github.com/justinhblee-prog/shorts/pull/475) final docs/task-ledger head `c43884bcbdb67ff79031b3025fe3e8f02a8c7be3` passed Backend [44894928685](https://github.com/justinhblee-prog/shorts/actions/runs/44894928685), **962 tests**, and Compose [44894928693](https://github.com/justinhblee-prog/shorts/actions/runs/44894928693). Live provider acceptance remains blocked by credentials, spend approval, legal/provider review and private test accounts.
- Compose cleanup PR [#477](https://github.com/justinhblee-prog/shorts/pull/477) exact head `5924e6027e3e65ac6398486e17c3f17bc25f6f83` passed Compose [44893900087](https://github.com/justinhblee-prog/shorts/actions/runs/44893900087) and verified clean profile-aware teardown.
- Windows worker PR [#416](https://github.com/justinhblee-prog/shorts/pull/416) head `604fff33a23f1d271a7f7c6183d44b7f21e6f909` passed Backend [44851183939](https://github.com/justinhblee-prog/shorts/actions/runs/44851183939). DEV-ORCH-008 PR [#445](https://github.com/justinhblee-prog/shorts/pull/445) reconciled its base at `1da9824a05983b0c7ef679a586403c7d0c55b49d`, 15 ahead / 0 behind, mergeable; exact-head Backend [44895214665](https://github.com/justinhblee-prog/shorts/actions/runs/44895214665) passed **629 tests**. Real Windows runner, shared SQLite file and OS isolation remain unverified.
- All PRs remain Draft/open/unmerged. No production deployment, live provider call, public publishing, workflow dispatch, runner/secret change or production data deletion was performed.
