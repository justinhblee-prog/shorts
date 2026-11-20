# NEXUS STUDIO PRO — Integration handover (2026-11-20)

**Baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Verified integration candidate:** PR #407, head `77333d264a123d80c87e6ca13f1edfc0282be06a`  
**Status:** hosted exact-head CI passed; Draft/unmerged; no production deployment or live provider/OAuth operation.

## 1. Current integrated state

PR #407 combines the dependency-aligned Core/Policy/quarantine-recovery candidate from PR #406 with the modern analytics dashboard UI chain (#395–#399).

Verified at the exact head above by GitHub Actions run [44589059999](https://github.com/justinhblee-prog/shorts/actions/runs/44589059999):
- 880 backend tests passed.
- `scripts/validate.sh` passed.
- `node --check frontend/app.js` passed.
- Analytics Chromium smoke passed: all 19 dashboard modules reached API-connected state; pagination, full CSV export, responsive/keyboard behavior, and partial-failure feedback passed.
- Audited quarantine-recovery Chromium smoke passed: authenticated operator confirmation, ready-state transition, and immutable audit attribution.
- Browser artifact: [14564045600](https://github.com/justinhblee-prog/shorts/actions/runs/44589059999/artifacts/14564045600).

This is hosted fixture validation, not production/runtime validation. PR #407 remains Draft and unmerged.

## 2. Integrated UI and backend capabilities

- Analytics history: 25-row pagination, keyboard-accessible navigation, 14 explicit column scopes, full 502-row CSV export.
- Dashboard: 19 modules, API connection state, responsive desktop/mobile layout, intentional partial API failure feedback.
- Development control plane: worker/job metrics, event history, persistent job visibility, operator-confirmed quarantine recovery.
- Recovery API: authenticated `operations.manage` authorization, actor binding to the token-authenticated principal, explicit reason/confirmation, immutable audit event.
- Analytics backend: freshness/history endpoints, bounded history queries, immutable YouTube history snapshots, TikTok history indexes and bounded queries.
- Existing Core/Policy changes retained: dependency-aligned recovery, fail-closed policy declaration validation and approval preflight, synthetic-media disclosure, feed-scoped GitHub pagination.

## 3. Existing engineering automation state

The development-job control plane includes a durable SQLite job graph, dependency-aware scheduling, leases/heartbeats/fencing, retries/quarantine, read-only GitHub intake, scoped Aider/Ollama execution, worktree evidence verification, Draft PR publication verification, bounded continuation, and a read-only dashboard.

Important distinction: hosted CI validates code and fixtures only. The Windows self-hosted runner, Ollama `qwen2.5-coder:7b`, persistent LocalAppData database across separate runs, real model-generated changes, verified Draft PR publication, and dependent-job advancement have not been demonstrated end-to-end.

## 4. Next work, ordered by dependency

1. **Review the integration candidate:** inspect PR #407 diff and dependency chain (#406 plus UI #395–#399). Keep Draft; do not merge automatically.
2. **Windows runner preflight:** verify runner version >= 2.327.1, Python 3.11+, Git Bash, Node 18+, Ollama API, exact model tag, and isolated backend/Aider virtual environments on the trusted Windows host.
3. **Persistence proof:** execute two separate workflow runs and verify the same LocalAppData SQLite database, durable job/event state, and clean workspace lifecycle.
4. **Real autonomous cycle:** demonstrate a scoped Ollama-generated code+test diff, passing repository validation, exact open Draft PR URL/head/file-list verification, durable review-artifact recording, and dependent-job advancement.
5. **Dashboard against real runner state:** verify worker heartbeat, lease/job/event state and operator recovery using the actual runner, not fixtures.
6. **Product release gates:** real provider compatibility, OAuth consent/scopes, media artifact download/staging, live YouTube/TikTok behavior, revenue/cost reconciliation, and production deployment remain separate operator-approved gates.

## 5. Parallel work rules

- UI/dashboard, backend domain modules, and test/documentation work may proceed in parallel only when declared file/resource scopes are disjoint.
- Serialize shared schemas, migrations, central API contracts, workflow files, and same-module changes.
- Keep one integration lane to assemble outputs and run full exact-head validation.
- Every completed job needs a meaningful source diff, regression test, exact validation result, and review artifact.
- No-op runs are not completions. Hosted CI success is not proof of live runtime behavior.
- Draft PRs only. No automatic merge, deployment, secret changes, public publishing, destructive migration, or paid-provider action.

## 6. Latest known boundaries

- PR #407: Draft/unmerged; exact-head hosted validation passed as listed above.
- Windows runner and local Ollama: unverified.
- Live provider/OAuth and production deployment: unverified.
- Do not claim background execution while this chat is idle; scheduled continuation requires the workflow to be deliberately integrated into the default branch and a trusted runner to be online.


## 7. Worker tooling worktree isolation — verified 2026-11-20

PR #409 (`fix/nexus-runner-venv-outside-worktree`) addresses a startup deadlock in the trusted Windows worker: the backend and Aider virtual environments were previously created inside `GITHUB_WORKSPACE`, while the executor correctly rejects any untracked worktree content before claiming a job.

- Both environments now live under persistent `%LOCALAPPDATA%\NexusStudioPro\tooling` (with a `%USERPROFILE%\AppData\Local` fallback), outside the checkout and the SQLite state directory.
- Existing complete environments are reused; incomplete environment directories fail closed rather than being deleted/rebuilt implicitly.
- Workflow contract regressions verify both paths, fallback behavior, and retention of the clean-worktree guard.
- Exact PR #409 head: `4d7286a7a4472736c0c037a34cff36743c54ae69`.
- Hosted workflow [44592757768](https://github.com/justinhblee-prog/shorts/actions/runs/44592757768) passed: `scripts/validate.sh`, frontend syntax, analytics Chromium smoke, recovery Chromium smoke, and screenshot artifact upload [14564576167](https://github.com/justinhblee-prog/shorts/actions/runs/44592757768/artifacts/14564576167).
- PR #409 is Draft/unmerged. Hosted Linux validation does not prove Windows path/runtime behavior, LocalAppData persistence, or a live Ollama cycle.

The next engineering gate remains the ordered Windows runner preflight and two-run persistence proof in section 4.


## 8. Aggregate exact-head validation — 2026-11-20

- Aggregate PR #415 head `cb67ee8505ca508dddbb753761d4954a8a345fc9` passed two independent exact-head hosted runs: [44601341416](https://github.com/justinhblee-prog/shorts/actions/runs/44601341416) and [44601350386](https://github.com/justinhblee-prog/shorts/actions/runs/44601350386). Each completed all 17 workflow steps successfully, including repository validation, frontend syntax, analytics Chromium smoke, dependency/recovery Chromium smoke, and artifact upload.
- Browser artifact archive: [14566419852](https://github.com/justinhblee-prog/shorts/actions/runs/44601341416/artifacts/14566419852). Desktop and 320px mobile screenshots were retrieved and visually inspected.
- PR #415 includes parent dashboard/API changes, workstream/dependency UI, DAG mutation guards, Windows tooling path-integrity guards, and the multi-flow handover documents.
- This hosted validation does not prove execution on the trusted Windows self-hosted runner, persistence across two actual runner jobs, or a live Ollama generation cycle. Those remain external BLOCKED gates.
- PR #415 remains Draft/open/unmerged. No merge or deployment was performed.


## 9. Aggregate candidate continuation and runner activation dependency — 2026-11-20

- Aggregate PR #415 head `b3db65d7b1391f107c6b1ca5ae3448e61d4cac9d` passed exact-head hosted workflow [44643755871](https://github.com/justinhblee-prog/shorts/actions/runs/44643755871): 17/17 steps, zero failures. Its browser artifact [14586849009](https://github.com/justinhblee-prog/shorts/actions/runs/44643755871/artifacts/14586849009) was retrieved; desktop and mobile screenshots were visually inspected.
- Follow-up documentation commit `87639d8f6c83405df4cac46209f5b1808e8bc5a3` records the Windows worker activation constraint in MULTI_FLOW_EXECUTION. Its exact-head hosted workflow [44644264702](https://github.com/justinhblee-prog/shorts/actions/runs/44644264702) passed all 17 steps.
- Important activation dependency: the worker workflow currently exists on the unmerged integration branch. GitHub requires a `workflow_dispatch` workflow to exist on the default branch for manual dispatch; scheduled workflow evaluation also uses the default branch. Therefore the Windows/Ollama workflow cannot be triggered from this candidate until an authorized default-branch change makes it available.
- The available repository connection supports run inspection and reruns but does not expose workflow dispatch. No Windows run, LocalAppData two-run persistence, or live Ollama generation is claimed.
- PR #415 remains Draft/open/unmerged. Default-branch workflow activation, merge, deployment, and external provider operations remain gated; no changes to the default branch were made.


## 10. Aggregate browser verification — 2026-11-20

- Aggregate browser workflow run [44646542482](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482) completed successfully on code head `8b45c77f54439819073de8f631097d3963b1bd20`; every workflow step succeeded.
- Passed `scripts/validate.sh`, `node --check frontend/app.js`, Playwright installation, Chromium installation, `scripts/ui_browser_smoke.mjs`, `scripts/ui_recovery_browser_smoke.mjs`, and browser artifact upload.
- Dashboard browser coverage: authenticated dashboard/API fixture, all 19 modules connected, review approval and audit history, analytics history pagination and full CSV download, partial API failure feedback, keyboard navigation, browser back/forward, reduced motion, responsive desktop/mobile layout and 320px overflow/touch-target checks.
- Recovery browser coverage: UI/Core workstream lanes, persisted completed prerequisite and dependent quarantined job, 320px dependency-board layout, operator-confirmed recovery, ready-state transition, and immutable audit attribution.
- Artifact [14589176582](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482/artifacts/14589176582) contains `nexus-dashboard-desktop.png` (1440px) and `nexus-dashboard-mobile.png` (320px). Both screenshots were retrieved and visually inspected.
- The font installation stall was resolved by bounding the font setup to five minutes, using bounded APT retries/timeouts, and allowing the fallback-font installation to fail without suppressing the subsequent browser tests. In this run the font setup itself succeeded.
- This is hosted Linux + deterministic API-fixture browser validation, not proof of trusted Windows runner execution, LocalAppData persistence, live Ollama generation, OAuth/provider behavior, real media rendering, or live publishing.
- PR #415 remains Draft/open/unmerged. No merge, deployment, default-branch change, or external provider action was performed.


## 11. CI font setup reliability adjustment — 2026-11-20

- The optional Noto CJK package installation caused repeatable stalls on hosted APT mirror access, even with step timeout and bounded subprocess attempts.
- Removed the network-dependent APT update/install from the browser-test workflow. The workflow now performs a fast, non-failing font availability check and proceeds with the runner fallback when Noto CJK is absent.
- This affects screenshot font selection only; it does not weaken application assertions or browser test coverage. The earlier successful artifact [14589176582](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482) already contains visually inspected Korean desktop/mobile screenshots.
- The updated workflow must still pass a fresh exact-head CI run before this adjustment is considered verified. Do not mark its run PASS before both browser smoke scripts and artifact upload finish.


## 12. Network-independent browser CI exact-head PASS — 2026-11-20

- Exact aggregate workflow run [44647416771](https://github.com/justinhblee-prog/shorts/actions/runs/44647416771) passed all workflow steps on head `5412806bd2ac885211f75710a5378c8084842da5`: repository validation, frontend syntax, font-availability check, Playwright/Chromium setup, dashboard browser smoke, recovery/dependency browser smoke, and artifact upload.
- Artifact [14589437372](https://github.com/justinhblee-prog/shorts/actions/runs/44647416771/artifacts/14589437372) was downloaded and inspected. The runner did not have Noto CJK, so this run's screenshots use the fallback font and render some Korean glyphs as tofu. Do not use this artifact as the visual typography reference.
- The earlier artifact [14589176582](https://github.com/justinhblee-prog/shorts/actions/runs/44646542482) contains readable Korean desktop/mobile screenshots from the same integrated UI code; both images were retrieved and visually inspected. Use that artifact for visual review.
- The workflow no longer depends on external APT mirrors. This removes a recurring CI stall at the cost of not guaranteeing Korean glyph rendering in every hosted runner screenshot. Browser assertions remain fully active and passed.
- Hosted CI still does not verify Windows self-hosted execution, LocalAppData two-run persistence, live Ollama generation, OAuth/provider behavior, real media rendering, or live publishing.


## 13. UI workstream board coverage expansion — 2026-11-20

- The existing dashboard already rendered real persisted job dependencies and grouped jobs by scope; prior handover queue wording understated the implementation.
- Added persisted browser fixtures for Automation, QA, Docs, mixed-scope Integration, and unclassified jobs.
- Expanded recovery-browser assertions for all seven workstream groups and their visibility at a 320px viewport, while retaining the dependency and recovery/audit checks.
- Code commits: `cb627da0ae91934ccebbcc3cb602054efd78b39c`, `03bb8a8cf23ecf5d98468696e5ca35b7cc19d029`.
- CI runs 44652238309, 44652246574, 44652255170 are pending exact-head completion; no PASS is claimed yet.
- Remaining UI refinement: visually communicate dependency edges/ancestors and explicitly represent prerequisite IDs not included in the current API page.

- Follow-up UI refinement: prerequisite chips are keyboard-operable navigation controls that scroll to and focus the persisted parent job card; unresolved IDs outside the current page are visibly labeled. Static frontend assertions and Chromium click/Enter checks were added.

- A browser regression initially exposed that the list endpoint did not return dependency IDs: the store's single-job `get()` included them, but `list()` omitted them. Corrected `DevelopmentJobStore.list()` to fetch dependency edges for the returned IDs in one query and added a backend regression test.
- Exact head `c2fab8b8b7bc3abcfe7cf9b96c83206d8d508a10` passed full backend validation, frontend syntax, dashboard and recovery/workstream/dependency-navigation Chromium smoke tests, and artifact upload in [run 44652954128](https://github.com/justinhblee-prog/shorts/actions/runs/44652954128). Browser artifact: [14591602484](https://github.com/justinhblee-prog/shorts/actions/runs/44652954128/artifacts/14591602484).

## 14. Core DAG automatic-transition audit hardening — 2026-11-20

- Reviewed lease fencing, dependency release, retry transitions, and immutable event history in backend/development_jobs.py.
- Found missing audit records for the automatic retry_wait → ready and blocked → ready transitions inside claim_ready(). Added one immutable event per successful transition: retry_due and dependencies_satisfied.
- The transitions and their events share the existing immediate SQLite write transaction. Conditional updates retain state guards; dependency release requires a non-empty dependency set and all parents completed.
- Added regression assertions to backend/tests/test_development_jobs.py. Initial CI caught a test ordering issue because a subsequent claim event is appended after dependency release; the assertion was corrected to inspect the preceding event.
- Exact head 07b31e6e1180bcfb1e191d2a88b079b9953cacb4 passed full backend validation (895 tests), frontend syntax, dashboard Chromium smoke, recovery/workstream/dependency-navigation Chromium smoke, and artifact upload in run 44653917688. Artifact: https://github.com/justinhblee-prog/shorts/actions/runs/44653917688/artifacts/14591668407.
- No Windows/Ollama/provider/live-publishing validation is implied. PR #415 remains Draft/open/unmerged.

## 15. DAG mutation/claim race regression — 2026-11-20

- Added a synchronized race test for add_dependency() versus claim_ready() while the prerequisite is held by another worker.
- The invariant is that a child cannot become leased and simultaneously gain an unresolved dependency: either dependency insertion commits first and the child remains blocked, or the worker claim commits first and dependency insertion is rejected by the active-job mutation guard.
- Exact head 8a5364903526cc8ed56977bdec730206b514f778 passed full hosted CI in [run 44654439190](https://github.com/justinhblee-prog/shorts/actions/runs/44654439190), including backend validation, frontend syntax, both Chromium smoke suites, and artifact upload [14592966229](https://github.com/justinhblee-prog/shorts/actions/runs/44654439190/artifacts/14592966229).
- This proves the tested SQLite transaction boundary under concurrent test threads; it does not establish Windows runner isolation or cross-process LocalAppData persistence. PR #415 remains Draft/open/unmerged.

## 16. UI job selection/detail interaction verification — 2026-11-20

- Expanded scripts/ui_recovery_browser_smoke.mjs to verify that selecting a development job marks its action button aria-pressed=true, selecting another job with Enter clears the previous selection, and the event-detail panel refreshes to the selected job's distinct event history.
- Exact head 17ee4a515767b9e05b5c20b00eb240024365f807 passed all PR CI steps in [run 44654934989](https://github.com/justinhblee-prog/shorts/actions/runs/44654934989): backend validation, frontend syntax, dashboard Chromium smoke, recovery/workstream/dependency-navigation and keyboard-selection/detail-switching smoke, artifact upload [14592123441](https://github.com/justinhblee-prog/shorts/actions/runs/44654934989/artifacts/14592123441).
- This is hosted Chromium against deterministic API fixtures; it verifies the interaction contract, not a live authenticated production environment.
