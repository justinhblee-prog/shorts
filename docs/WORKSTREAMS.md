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
