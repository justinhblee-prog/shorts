# NEXUS STUDIO PRO — Parallel Workstreams

**Coordination baseline:** `813dfb74fc7c5243dc35f1c3dbdb67c58d9a066b`  
**Core workstream:** `build/build-00315-harden-tiktok-aigc-disclosure` (existing Draft PR #323)  
**UI workstream:** `ui/nexus-dashboard-workspace` (this branch)

## Goal

Develop the product interface and its runtime independently so both can make progress without waiting for the other. Integrate through explicit API contracts and end-to-end validation.

## Ownership boundaries

| Workstream | Owns | Avoids |
|---|---|---|
| UI | `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `frontend/cyber-magic*`, frontend-focused tests and UI docs | Backend routes, persistence schemas, worker/provider behavior |
| Core | `backend/**`, database schema and migrations, worker/scheduler/provider integrations, backend tests and operational contracts | UI layout/styling unless a coordinated integration change is required |
| Integration | API contract docs, cross-layer regression tests, release/readiness notes | Uncoordinated edits to files owned by both tracks |

## Working rules

1. Keep Core work on PR #323 and UI work on this branch and its own Draft PR. Do not merge either PR without explicit approval.
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
- PR #323 remains Open / Draft / Unmerged and is the current Core delivery line.
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
