# NEXUS STUDIO PRO — Parallel Workstreams

**Coordination baseline:** `851b414262cc6bef8ec374ed0e7a25921521b295` (main snapshot, 2026-11-19)  
**Core delivery:** stacked BUILD / POLICY Draft PR chains #381, #383–#386, #388–#390  
**UI delivery:** UI Draft PRs #382 and #387; UI base chain remains separate

## Goal

Develop the product interface and its runtime independently so both can make progress without waiting for the other. Integrate through explicit API contracts and end-to-end validation.

## Ownership boundaries

| Workstream | Owns | Avoids |
|---|---|---|
| UI | `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `frontend/cyber-magic*`, frontend-focused tests and UI docs | Backend routes, persistence schemas, worker/provider behavior |
| Core | `backend/**`, database schema and migrations, worker/scheduler/provider integrations, backend tests and operational contracts | UI layout/styling unless a coordinated integration change is required |
| Integration | API contract docs, cross-layer regression tests, release/readiness notes | Uncoordinated edits to files owned by both tracks |

## Working rules

1. Keep Core and UI changes in their own Draft PR branches and preserve documented dependencies. Do not merge any PR without explicit approval.
2. One owner per file at a time. Cross-boundary changes are split into separate commits or coordinated through a documented contract first.
3. UI consumes existing documented API shapes. If a required field or endpoint is missing, record the contract gap and request a Core-side implementation rather than inventing mock success.
4. Core changes preserve stable API semantics or document compatible changes before UI adoption.
5. Each workstream runs its own focused tests. Integration validation runs after both sides are ready.
6. Mark browser, OAuth, AI-provider, publishing, and production-scale checks as unverified unless executed against the real target environment.

## Work sequence

- **UI lane:** information architecture, dashboard/workspace usability, responsive layout, accessible interactions, real API loading/error/empty states, browser validation.
- **Core lane:** remaining storage/query performance, collection reliability/recovery, provider and worker correctness, security, API contract tests.
- **Integration lane:** connect real endpoints, exercise create → review → approve → publish → analytics flows, fix regressions, update handover and release readiness.

## Current baseline

- The repository already contains a single-page dashboard with Studio, Discovery, Review, and Operations sections.
- Analytics history filters, charts, and CSV export are implemented in the frontend; live browser behavior and real provider account behavior are not established by source tests alone.
- PR #323 is no longer the sole Core delivery line; current work is split across the active BUILD and POLICY stacks listed below.
- This document establishes ownership and branch boundaries; it does not claim that two independent agents are executing simultaneously.


## UI-00002 — keyboard navigation and focus visibility

- Add a keyboard-only skip link to the main content so keyboard users can bypass the sticky workspace header.
- Add explicit high-contrast `:focus-visible` outlines for links, buttons, and form controls; the skip link becomes visible when focused.
- Add source regression coverage for the skip link and focus treatment.
- Browser keyboard traversal and assistive-technology validation remain outstanding.

- UI PR merge-result validation initially inherited a Core SQL aggregation regression from the base branch; Core corrected the response mapping in commit `c17ee8661b7a830a4f55e97d57eab4e163b65ae5`. Re-run the UI merge-result workflow against the corrected base before treating this UI checkpoint as validated.


## UI-00003 — touch navigation clarity and responsive refinements

- Add localized native tooltips to the five workspace navigation links, preserving their accessible names and active-section behavior.
- Label the main landmark in Korean for assistive technology.
- Refine compact desktop spacing and mobile touch target dimensions for navigation and connection controls.
- Add source regression coverage for localized tooltips and the main landmark label.
- Actual mobile/desktop browser and assistive-technology validation remain outstanding.


## UI-00004 — compact navigation touch and status accessibility

- Localize the workspace navigation landmark for Korean screen-reader users.
- Expose API connection changes as a polite live status announcement.
- Make the main skip-link destination programmatically focusable.
- Preserve minimum 48px navigation targets and 44px refresh action targets in the icon-only compact layout.
- Add source-level regression coverage. Actual touch-device and screen-reader verification remain outstanding.


## Active FLOW snapshot — 2026-11-20

This snapshot is a repository coordination record, not a claim that independent agents are continuously executing. Work advances through bounded jobs, with each lane verified independently and integration performed only after dependency gates pass.

### UI lane
- PR #382 — UI-00011 browser-history navigation synchronization; Draft, unmerged; exact-head browser smoke and Compose checks passed in hosted CI.
- PR #387 — UI-00012 audited quarantine-recovery control; Draft, unmerged; depends on PR #384. Exact-head validation passed; live authenticated browser/API interaction remains unverified.

### Core worker / orchestration lane
- PR #381 BUILD-00384 → #383 BUILD-00385 → #384 BUILD-00386 form the worker-safety chain: durable scope semantics, worktree-diff verification, then audited operator recovery.
- PR #385 BUILD-00387 adds approved YouTube synthetic-media disclosure mapping on the #383 base.
- PR #388 BUILD-00388 is a sibling follow-up on #384, constraining GitHub intake pagination to the original HTTPS API host and collection path and rejecting non-canonical or hostile imported issue links.

### Policy lane
- PR #386 POLICY-00001 → #389 POLICY-00002 → #390 POLICY-00003 form the policy-validation chain: declaration object validation, source URL/rights-key validation, then fail-closed review approval for script-bearing production artifacts.
- PR #390 exact head `a89dd228f924bf6f7cb8bd7d441c6733851c1acf` passed hosted repository validation and frontend syntax checks in runs [44554183308](https://github.com/justinhblee-prog/shorts/actions/runs/44554183308) and [44554192636](https://github.com/justinhblee-prog/shorts/actions/runs/44554192636).

### Integration / release gates
- All PRs #381–#390 remain Draft and unmerged at this snapshot; their base/head relationships must be preserved when reviewing or promoting stacks.
- No production deployment, live OAuth/provider upload, live Windows self-hosted runner execution, or real quarantined-job recovery is claimed.
- Hosted CI success validates the tested source revision only. It does not imply the scheduled local worker is active on main or that independent worker processes are running.
- Integration must verify API contract compatibility, database migration ordering, permission grants, browser behavior, and release-readiness evidence before any merge or deployment.


## Active UI design continuation — 2026-11-20 01:24 KST

- PR #392 — UI-00013 cinematic dashboard presentation layer; Draft, unmerged. Exact head `454698508fbe652a511d2ad1235c274aea3bcd53` has successful hosted CI run [44563818798](https://github.com/justinhblee-prog/shorts/actions/runs/44563818798).
- PR #394 — UI-00014 professional workspace design system; Draft, unmerged, stacked directly on PR #392. Its six-commit delta is limited to `frontend/cyber-magic.css` and `frontend/index.html`; it preserves the existing app JavaScript/API behavior. Exact head `b098826455150fefe4a8def6377bf77630a1ad7f` has one successful full validation + Chromium browser smoke run [44565614418](https://github.com/justinhblee-prog/shorts/actions/runs/44565614418), including screenshot artifact `nexus-dashboard-browser-screenshots`; a second duplicate run [44565685710](https://github.com/justinhblee-prog/shorts/actions/runs/44565685710) is still in progress at the Korean font setup step as of this snapshot.
- Do not merge or deploy either UI PR. The next UI action is to inspect the captured desktop/mobile screenshots and finish the second exact-head CI run; then review visual hierarchy, responsive behavior, and preservation of existing controls before integration.
- The UI stack must be integrated only after the current Core/Policy dependency stack is reviewed and the cross-lane API/browser regression plan is satisfied.

## UI-00015 — analytics history table pagination

- PR #395 — Draft, unmerged, stacked on UI-00014 / PR #394. Head currently `6afe85c0e31cb0a478fe1159c10d303f75800535`.
- Browser screenshot review of UI-00014 exposed a long analytics history table: the view displayed up to 200 records in one continuous table, making the overall workspace excessively tall.
- UI-00015 changes only the analytics history presentation: 25 rows per page, previous/next controls, and a live page/count indicator. Chart summaries and full cursor-paginated CSV export remain independent of the visible page.
- Added browser smoke assertions for 25-row rendering, page 1 → 2 → 1 navigation, disabled previous control on the first page, and preservation of the complete 502-row CSV export.
- Latest-head hosted repository validation is passing through `scripts/validate.sh` in [run 44567584068](https://github.com/justinhblee-prog/shorts/actions/runs/44567584068); full Compose image build, service startup/readiness, scheduled backup and isolated restore passed in [run 44567584065](https://github.com/justinhblee-prog/shorts/actions/runs/44567584065). A follow-up browser run initially exposed that the API returns 501 snapshots while the legacy table intentionally caps visible rows at 200; the current head restores that 200-row cap and paginates those rows. The browser smoke now also reloads the analytics history and verifies 25-row pagination controls fit and navigate at a 320px viewport. The latest exact-head repository and Chromium browser checks are running. An earlier validation failure from a stale source assertion was corrected and is not the current head.
- Do not merge PR #395 independently. Keep the UI-00013 → UI-00014 → UI-00015 stack intact until browser validation and cross-lane integration review pass.


## UI-00015 exact-head completion — 2026-11-20

- PR #395 remains Draft/unmerged, head `bd2926c981c44398465994d4825d981729bf4e13`, stacked on #394.
- Backend + Chromium browser smoke passed in [run 44570606677](https://github.com/justinhblee-prog/shorts/actions/runs/44570606677). The log confirms dashboard/API authentication, review approval/audit history, analytics pagination at desktop and 320px mobile, complete 502-row CSV download, partial API failure feedback, browser history, responsive and keyboard checks.
- Compose integration passed in [run 44570606778](https://github.com/justinhblee-prog/shorts/actions/runs/44570606778), including service readiness, encrypted scheduled backup, isolated restore and SQLite integrity check.
- Screenshot artifact [14554042466](https://github.com/justinhblee-prog/shorts/actions/runs/44570606677/artifacts/14554042466) contains 1440px desktop and 320px mobile captures; both were downloaded and visually inspected. The browser log independently confirms mobile pagination fit/navigation.
- Apt font installation was removed from the workflow in the exact head to eliminate a network-dependent CI stall. PR description and DEVELOPMENT_AND_VALIDATION.md now record exact-head evidence.
- Preserve the UI-00013 → UI-00014 → UI-00015 Draft stack. Do not merge or deploy without review/approval. Live OAuth/provider publishing remains unverified.


## Exact-head validation refresh — 2026-11-20 02:10 KST

- BUILD-00386 / PR #384: exact head `6f8f378b8e8e343919af3a4aaba585c90ae6f00d`, backend CI passed ([44557449271](https://github.com/justinhblee-prog/shorts/actions/runs/44557449271)).
- BUILD-00387 / PR #385: exact head `151ee074d8116e12759a6dc46e734cf84f52c2d4`, backend CI passed ([44563227397](https://github.com/justinhblee-prog/shorts/actions/runs/44563227397)).
- POLICY-00001 / PR #386: exact head `7a83fe9960c3581ad18ddd25805c5f3aa35afc03`, backend CI passed ([44550380614](https://github.com/justinhblee-prog/shorts/actions/runs/44550380614)).
- UI-00012 / PR #387: exact head `13ab5be32c108118aa57512bce1ac1bd17726ae8`, backend CI passed ([44555664708](https://github.com/justinhblee-prog/shorts/actions/runs/44555664708)).
- BUILD-00388 / PR #388: exact head `f55030dab87cbcb8a1fa1a015a74db87961496f4`, repository validation and frontend syntax passed ([44558169681](https://github.com/justinhblee-prog/shorts/actions/runs/44558169681)).
- POLICY-00002 / PR #389: exact head `d38bca36389c439d4cf37de31d9dfc4d72d53780`, backend CI passed ([44552071509](https://github.com/justinhblee-prog/shorts/actions/runs/44552071509)).
- POLICY-00003 / PR #390: exact head `cc29af580467e6b261fa724aad99a976eedb5552`, backend CI passed ([44560114906](https://github.com/justinhblee-prog/shorts/actions/runs/44560114906)).
- UI-00014 / PR #394: exact head `b098826455150fefe4a8def6377bf77630a1ad7f`, both full validation/browser runs passed ([44565614418](https://github.com/justinhblee-prog/shorts/actions/runs/44565614418), [44565685710](https://github.com/justinhblee-prog/shorts/actions/runs/44565685710)).
- UI-00015 / PR #395: exact head `bd2926c981c44398465994d4825d981729bf4e13`, backend/browser and Compose integration passed ([44570606677](https://github.com/justinhblee-prog/shorts/actions/runs/44570606677), [44570606778](https://github.com/justinhblee-prog/shorts/actions/runs/44570606778)).

PR #388 job logs confirm `scripts/validate.sh` and `node --check frontend/app.js` succeeded. All PRs remain Draft/unmerged. Full integration is not yet complete: current lifecycle tests use mocked providers and the independently stacked Core/Policy/UI branches have not been tested together on one candidate commit. The next integration job must preserve stack dependencies and explicitly cover audited quarantine recovery through the UI/API boundary.


## Integration checkpoint — quarantine recovery contract (2026-11-20 02:05 KST)

- PR #397 adds three API-handler regressions on top of UI-00012 / PR #387: reject read-only operators before store mutation (403), map missing jobs to 404, and reject blank recovery reasons as 422.
- Exact head `f0c2ff4d0e8a27494cf48e6be2333808e0997e5c` passed hosted backend validation in [run 44573305813](https://github.com/justinhblee-prog/shorts/actions/runs/44573305813), including `scripts/validate.sh` and `node --check frontend/app.js`.
- The tests call the FastAPI route function with the store mocked. This is handler-contract coverage, not a live HTTP/browser interaction or a real operator recovery.
- PR #397 is Draft, unmerged, and based on PR #387; preserve the #384 → #387 → #397 dependency order.
- PR #385 remains at exact head `151ee074d8116e12759a6dc46e734cf84f52c2d4`; its hosted backend run [44563227397](https://github.com/justinhblee-prog/shorts/actions/runs/44563227397) passed. Do not substitute an uncommitted or historical hardening head for the actual PR head.
- Cross-lane integration remains blocked until the dependency-ordered Core, Policy and UI branches are assembled on one candidate commit and tested together. No merge/deployment or live provider action is authorized.


## UI-00016 pagination accessibility checkpoint (2026-11-20)

- PR #398 adds a named navigation landmark to analytics-history pagination and browser coverage for keyboard Enter activation, last-page rendering, next-button disabling at the final page, and return to page 1.
- Exact head `0d9db34cc5969f277c1174f7092e7d4907f957af` passed the complete hosted backend/browser workflow [44573923657](https://github.com/justinhblee-prog/shorts/actions/runs/44573923657). The run completed `scripts/validate.sh` and the browser smoke, including 320px mobile navigation, the 25-row page behavior, full 502-row CSV export, review approval/audit history, and no browser page errors.
- Browser screenshots artifact: [14555931151](https://github.com/justinhblee-prog/shorts/actions/runs/44573923657/artifacts/14555931151).
- PR #398 remains Draft/unmerged and is stacked on UI-00015 / PR #395. No production deployment or live provider publishing was exercised.


## UI-00017 analytics table header semantics (2026-11-20)

- PR #399 adds explicit `scope="col"` semantics to all 14 analytics history table headers and checks all 14 in the Chromium browser smoke test.
- The first hosted run [44574589707](https://github.com/justinhblee-prog/shorts/actions/runs/44574589707) exposed one stale source regression assertion expecting the old unscoped header markup. Updated that assertion to match the explicit column scope; the subsequent exact-head run is [44574846265](https://github.com/justinhblee-prog/shorts/actions/runs/44574846265) (backend validation passed; browser smoke was still running at documentation update time).
- Compose integration run [44574846267](https://github.com/justinhblee-prog/shorts/actions/runs/44574846267) passed service readiness and isolated backup/restore checks; final cleanup was still running at documentation update time.
- PR #399 remains Draft/unmerged and is stacked on UI-00016 / PR #398. Do not mark complete until exact-head browser and Compose workflows finish successfully.


### UI-00017 final verification

- Corrected exact head `16d4964dcf2472f47c0b1dd1fbd890e2d46750c1` passed the complete hosted backend/browser workflow [44574846265](https://github.com/justinhblee-prog/shorts/actions/runs/44574846265), including `scripts/validate.sh`, Chromium browser smoke, and all 14 analytics column-header scope assertions.
- Compose workflow [44574846267](https://github.com/justinhblee-prog/shorts/actions/runs/44574846267) passed service readiness, scheduled backup, isolated restore, log collection and cleanup.
- Desktop/mobile screenshots artifact: [14556945683](https://github.com/justinhblee-prog/shorts/actions/runs/44574846265/artifacts/14556945683).
- PR #399 remains Draft/unmerged and based on UI-00016 / PR #398. Hosted CI and disposable Compose evidence only; no production deployment, real OAuth, or live provider publishing was exercised.


## BUILD-00388 — feed-scoped GitHub pagination rebased (2026-11-20)

- Original PR #388 was based on a stale BUILD-00386 ancestry and had diverged from the current quarantine-recovery base by five commits; GitHub reported it non-mergeable.
- Created successor PR #400 on `build/build-00386-quarantine-operator-recovery`, retaining the current base and transplanting only `backend/development_github_intake.py` plus `backend/tests/test_development_github_intake.py` from the original change.
- PR #400 exact head: `272d5efc9564b9d4dca6fa4bff187579a3911adb`; compare is cleanly ahead by two commits with zero behind and GitHub reports mergeable.
- Exact-head backend workflow [44575404874](https://github.com/justinhblee-prog/shorts/actions/runs/44575404874) was running at this checkpoint. Keep PR #400 Draft/unmerged until it passes. Original PR #388 is retained unchanged for traceability.


### BUILD-00388 exact-head verification

- PR #400 exact head `272d5efc9564b9d4dca6fa4bff187579a3911adb` passed hosted backend workflow [44575404874](https://github.com/justinhblee-prog/shorts/actions/runs/44575404874), including `scripts/validate.sh` and frontend JavaScript syntax validation.
- PR #400 remains Draft/unmerged on the current BUILD-00386 base. This is hosted CI evidence only; no live GitHub provider intake or production operation was performed.


## Policy stack base repair — POLICY-00001 through POLICY-00003 (2026-11-20)

- The original PR #386 was diverged from its YouTube disclosure base by 18 commits; the base and policy changes were independent at source level (YouTube publishing files versus policy-engine files). Created successor PR #401 on current PR #385 head, transplanting only `backend/policy_engine.py` and `backend/tests/test_policy_engine.py`. PR #401 is mergeable and exact-head checks passed [44575712933](https://github.com/justinhblee-prog/shorts/actions/runs/44575712933) and [44575735946](https://github.com/justinhblee-prog/shorts/actions/runs/44575735946).
- Created successor PR #402 on #401, transplanting policy-engine source URL and rights-key validation plus tests from original #389. It is mergeable; exact-head checks [44575784946](https://github.com/justinhblee-prog/shorts/actions/runs/44575784946) passed, while [44575810640](https://github.com/justinhblee-prog/shorts/actions/runs/44575810640) was still running at checkpoint.
- Created successor PR #403 on #402, carrying fail-closed review approval behavior and regressions from original #390. It is mergeable; exact-head runs [44575901354](https://github.com/justinhblee-prog/shorts/actions/runs/44575901354) and [44575928560](https://github.com/justinhblee-prog/shorts/actions/runs/44575928560) were running/queued at checkpoint.
- Original PRs #386, #389 and #390 remain unchanged for traceability. Successor PRs #401–#403 remain Draft/unmerged and preserve the dependency chain. No production deployment or live provider actions were performed.


## Quarantine recovery stack base repair — UI/API successors (2026-11-20)

- Original UI PR #387 was diverged from the current BUILD-00386 base. Successor PR #404 rebases the audited quarantine recovery dashboard controls onto current PR #384 and carries only frontend UI, markup, styling and frontend regression files. It is cleanly ahead by four commits, zero behind, and mergeable. Hosted checks [44576159819](https://github.com/justinhblee-prog/shorts/actions/runs/44576159819) passed; [44576203665](https://github.com/justinhblee-prog/shorts/actions/runs/44576203665) was still running at checkpoint.
- Original API contract PR #397 was based on the stale #387 branch. Successor PR #405 carries the API authorization/validation regression test onto #404; it is ahead by one commit, zero behind, and mergeable. Exact-head workflow [44576279441](https://github.com/justinhblee-prog/shorts/actions/runs/44576279441) was running at checkpoint.
- Original PRs #387 and #397 remain unchanged for traceability. Successors #404 and #405 remain Draft/unmerged. API tests use mocked storage and do not constitute live operator recovery.


### Quarantine recovery successor exact-head results

- PR #404 exact head `ee6a1113ce280c49c0a65c31e3555cf5a61de6d4`: both backend workflow runs [44576159819](https://github.com/justinhblee-prog/shorts/actions/runs/44576159819) and [44576203665](https://github.com/justinhblee-prog/shorts/actions/runs/44576203665) passed.
- PR #405 exact head `5dcfc199cd4d719b03601e1a3507f83689a7bbd0`: backend workflow [44576279441](https://github.com/justinhblee-prog/shorts/actions/runs/44576279441) passed.
- PRs #404 and #405 remain Draft/unmerged. The API contract tests use mocked storage; no live production recovery was performed.


## Core + Policy + UI integration candidate assembled (2026-11-20)

- Created Draft PR #406 on the exact BUILD-00385 base with one integration commit `96f59cc8b19792602f03eafd1c1138bde5c7b138` and 20 implementation/test files from the dependency-aligned successor branches.
- Included: BUILD-00386 recovery (#384), BUILD-00387 disclosure (#385), BUILD-00388 feed pagination (#400), POLICY-00001→00003 (#401→#403), and UI/API quarantine recovery (#404→#405).
- Candidate compare is cleanly ahead by one commit, zero behind; GitHub reports mergeable. Hosted exact-head runs [44576765212](https://github.com/justinhblee-prog/shorts/actions/runs/44576765212) and [44576807216](https://github.com/justinhblee-prog/shorts/actions/runs/44576807216) were queued/in progress at checkpoint.
- This is the first unified Core/Policy/UI source candidate; the cross-stack validation gate remains pending until both workflows complete. No merge, deployment or live provider operation was performed.


### PR #406 unified candidate backend validation result

- Exact candidate head `96f59cc8b19792602f03eafd1c1138bde5c7b138` passed hosted backend workflows [44576765212](https://github.com/justinhblee-prog/shorts/actions/runs/44576765212) and [44576807216](https://github.com/justinhblee-prog/shorts/actions/runs/44576807216).
- The detailed validation run executed `scripts/validate.sh`: **854 tests passed**, followed by `node --check frontend/app.js` success.
- Scope: unified backend/source regression plus JavaScript syntax. The candidate branch's workflow does not include Playwright browser smoke; separate UI branch browser checks (#399 and #404) are not a substitute for a browser run on this exact combined candidate.
- Candidate PR #406 remains Draft/unmerged. Full combined browser validation, production deployment, live OAuth/provider publishing and real operator recovery remain outstanding.


### PR #406 unified candidate — browser recovery verification passed

- Corrected exact candidate head: `04e52a4c6c06687b11ea17c7c45a2f9b561eeee0`.
- Both exact-head backend/browser runs [44577763179](https://github.com/justinhblee-prog/shorts/actions/runs/44577763179) and [44577785714](https://github.com/justinhblee-prog/shorts/actions/runs/44577785714) passed.
- `scripts/validate.sh`: **854 tests passed**; `node --check frontend/app.js` passed; Chromium recovery smoke passed authenticated dashboard load, quarantine state, operator prompt/confirmation, recovery to ready state, and immutable audit attribution.
- The browser runner is pinned to Ubuntu 24.04 because Playwright 1.56.1 does not support the GitHub Ubuntu 26.04 runner image. An initial 26.04 browser-install attempt failed before the smoke test; the pinned 24.04 exact-head runs passed.
- This closes the unified candidate's backend + targeted recovery-browser gate only. It does not validate the full analytics browser flow on this candidate, live YouTube/TikTok OAuth/publishing, production recovery, or deployment. PR #406 remains Draft/unmerged.


### UI-00017 + unified Core/Policy candidate integration audit (2026-11-20)

- Re-fetched the exact source files from UI-00017 / PR #399 (16d4964dcf2472f47c0b1dd1fbd890e2d46750c1), unified candidate PR #406 (04e52a4c6c06687b11ea17c7c45a2f9b561eeee0), and quarantine UI successor PR #404.
- Confirmed the two frontends are not interchangeable: PR #399 frontend/app.js and backend/tests/test_frontend.py contain analytics pagination/table semantics but no quarantine-recovery controls; PR #406/#404 contain recovery controls but not the UI-00017 analytics changes. The HTML/CSS files also differ materially.
- The branch comparison between UI-00017 and PR #406 reports diverged with 534 commits ahead and 519 behind, while PR #406's own dependency-base comparison is clean (ahead 7 / behind 0). Therefore a direct branch merge or wholesale copy of PR #404 frontend files would risk losing the analytics dashboard work and is explicitly rejected.
- No integration commit is claimed from this audit. Safe next implementation path: create a successor on the dependency-aligned UI stack base, transplant only PR #406's backend/Core/Policy file deltas, then perform a deliberate three-way frontend merge that preserves analytics pagination and adds recovery controls; retain both browser smoke scripts and execute both on the resulting exact head.
- Current verified evidence remains separate: PR #399 exact-head browser/Compose validation and PR #406 exact-head 854-test + recovery Chromium validation. They are not combined evidence. All feature PRs remain Draft/unmerged; no deployment or live provider operation.


### Follow-up integration preparation — analytics UI dependency chain (2026-11-20)

- Confirmed UI-00017 PR #399 is a five-commit successor of UI-00015 / PR #395 (`ui/ui-00015-analytics-history-pagination`), and #399 exact-head hosted workflows remain green: backend/browser `44574846265`, Compose `44574846267`.
- Created isolated scratch branch `integration/ui-analytics-quarantine-recovery-2026-11-20` from exact #399 head `16d4964dcf2472f47c0b1dd1fbd890e2d46750c1` as a safe staging point. No source files have yet been committed to this branch.
- Reconfirmed PR #406's exact-head backend workflow `44577785714` is green, and its recovery browser test passed as previously recorded. These results remain separate from the #399 UI evidence.
- The source review found that #399 already contains a substantial analytics-enabled portal (`frontend/app.js` 99,555 characters; `frontend/index.html` 23,632; `frontend/styles.css` 27,868; frontend source tests 22,219), whereas #404's recovery UI source is a materially older snapshot (`app.js` 77,840; `index.html` 21,528; `styles.css` 18,935; tests 12,211). Copying the old HTML or stylesheet wholesale is unsafe and would regress current dashboard content and styling.
- Recovery-specific code can be isolated in the old app source, but its dashboard markup and tests must be inserted into the newer document structure deliberately. The current connector's file retrieval did not provide all browser-smoke assets needed for a complete, locally executable merge/validation pass. No untested source patch was committed or described as complete.
- Next exact implementation: obtain the missing smoke assets and current markup anchors; port only the recovery card/handler/test additions onto the scratch branch; add both Playwright suites to the workflow; then run the exact combined head through full repository tests, analytics browser smoke and recovery browser smoke. Until then, integration remains open.


### Integration base correction — Core API dependency (2026-11-20)

- A deeper exact-file check of staging branch `integration/ui-analytics-quarantine-recovery-2026-11-20` confirmed that its `backend/app.py` does **not** define `POST /api/development/jobs/{job_id}/recover`. The branch was cut from UI-00017 (#399), which contains the analytics dashboard but not the BUILD-00386 recovery backend.
- The PR #406 recovery endpoint is not a standalone frontend patch: it imports `DevelopmentJobConflict`, calls `DevelopmentJobStore.recover_quarantined`, and requires the `operations.manage` permission. Its implementation depends on corresponding changes in `backend/development_jobs.py` and `backend/operator_rbac.py`, plus API/security tests.
- Therefore, simply porting #404's browser controls into the #399 branch would create a UI that calls a missing endpoint. That approach is rejected. Do not promote the existing scratch branch as an integrated candidate.
- Correct integration architecture: use PR #406's dependency-aligned Core/Policy tree as the backend base, then transplant the complete UI-00015 → UI-00016 → UI-00017 frontend/dashboard feature set from PRs #395 → #399, preserving #406's recovery panel/handler and its backend contract. This is a three-way frontend merge, not a frontend file replacement. Re-run both browser suites and full validation on one exact candidate head.
- PR #406's original integration commit `96f59cc8b19792602f03eafd1c1138bde5c7b138` carries 20 source/test file deltas; the later exact head `04e52a4c6c06687b11ea17c7c45a2f9b561eeee0` also corrects the recovery browser dialog handling. Existing #399 and #406 green runs remain separate evidence.
