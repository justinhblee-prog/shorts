# NEXUS STUDIO PRO — Release Readiness

**Snapshot:** 2026-11-21 15:42 KST  
**Product baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Inspected default-branch HEAD:** `c0bf340bd95e2485bc2c4eaf8ffe48d60943a6c4`  
**Decision:** **NOT READY FOR PRODUCTION RELEASE**

This ledger separates source implementation and isolated automated checks from real provider, account, deployment, operational and commercial verification. A green CI job is not evidence that a live external service works.

## Critical repository-governance blocker

The GitHub branch endpoint for `main` reported `protected=false`; the protection object reported `enabled=false` and required status-check enforcement `off`. The repository ruleset endpoint returned zero rulesets. Consequently, GitHub currently has no observed server-side rule requiring pull requests or passing CI before changes reach `main`.

**Required operator action:** in repository Settings, create a ruleset or branch-protection rule targeting `main` that requires pull requests, at least one approval, required CI checks, and blocks force-push and branch deletion. Review administrator/bypass exceptions so automation cannot bypass the rule. Re-read the branch and ruleset APIs after saving. Until this is confirmed, do not trust unattended repository writes. This snapshot itself made no changes to repository settings.

## Evidence snapshot

| Area | Observed evidence | Release assessment |
|---|---|---|
| Default branch CI | Inspected main HEAD has zero workflow runs and zero check-runs at snapshot time | Not verified |
| PR discipline | #311–#315 and #318 individually confirmed open, Draft, unmerged; first two 100-item open-PR pages all Draft; `draft:false` search returned zero | Compliant in inspected results; pagination beyond page 2 not independently enumerated |
| Cyber Magic UI | #417 visual-system branch and #463 responsive preview; backend CI passes on #463 head | Partial; final visual acceptance and exact-head browser smoke still required |
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
- Main HEAD `c0bf340bd95e2485bc2c4eaf8ffe48d60943a6c4`: no workflow run or check-run found at inspection time.

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

1. Operator: enable and verify branch protection/ruleset on `main` (required external action; not available through the current GitHub read/write tool surface).
2. Engineering: validate the integrated FFmpeg/render branch at its exact final head, including browser preview smoke and Compose artifact/review flow; do not infer completion from constituent PRs.
3. Engineering: verify Windows local Ollama runner registration and tool-call protocol without paid APIs, then confirm a single Draft PR round trip.
4. Operator: provide authorized deployment/provider/OAuth configuration only when a live-service validation window is explicitly approved.

No PR is merged, no direct push to `main` is performed, and no local PC folder or production data is changed by this checkpoint.
