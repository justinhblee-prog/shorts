# NEXUS STUDIO PRO — Parallel Workstreams

**Updated:** 2026-11-19  
**Core branch:** `build/build-00315-harden-tiktok-aigc-disclosure` — head `3a300622f7d8a7e0f6c134239c152156c55cc9fe`, Draft PR [#323](https://github.com/justinhblee-prog/shorts/pull/323)  
**UI branch:** `ui/nexus-dashboard-workspace` — head `5e86a432f7bdc42280d1293d3a52fa70eb95b057`, Draft PR [#329](https://github.com/justinhblee-prog/shorts/pull/329)

## Goal

Develop the product interface and its runtime independently so both tracks can progress without waiting for each other. Integrate through documented API contracts and end-to-end validation.

## Ownership boundaries

| Workstream | Owns | Avoids |
|---|---|---|
| UI | `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`, `frontend/cyber-magic*`, frontend-focused tests, browser smoke scripts and UI docs | Backend routes, persistence schemas, worker/provider behavior |
| Core | `backend/**`, database schema/migrations, worker/scheduler/provider integrations, backend tests and operational contracts | UI layout/styling unless a coordinated integration change is required |
| Integration | API contract docs, cross-layer regression tests, release/readiness notes | Uncoordinated edits to files owned by both tracks |

## Working rules

1. Keep Core work on PR #323 and UI work on PR #329. Both remain Open / Draft / Unmerged; do not merge without explicit user approval.
2. One owner per file at a time. Cross-boundary changes are split into separate commits or coordinated through a documented contract first.
3. UI consumes existing API shapes. If an endpoint or field is missing, record the contract gap and implement it in Core rather than inventing mock success.
4. Core preserves stable API semantics or documents compatible changes before UI adoption.
5. Each track runs focused tests. Integration validation runs after both sides are ready.
6. Browser, OAuth, AI-provider, publishing, and production-scale checks are marked unverified unless executed against the real target environment.
7. The UI branch is periodically synchronized with the Core branch using merge commits. This is branch-level parallel work, not a claim that two independent agents are executing simultaneously.

## Current product surface

The repository contains a single-page NEXUS STUDIO PRO dashboard with four primary workspaces: Studio, Discovery, Review, and Operations. Analytics history, charts, filtering and CSV export are part of the Operations workspace.

### UI completed work

- **UI-00001:** analytics-history loading, empty/success, API failure, paginated CSV progress, download-request completion and export-failure feedback.
- **UI-00002:** keyboard skip navigation and high-visibility focus styles.
- **UI-00003:** localized navigation tooltips, main landmark label and compact navigation refinements.
- **UI-00004:** polite connection-status announcements, focusable skip target and 48px/44px compact touch targets.
- **UI-00005:** analytics region `aria-busy` state and visible frozen API `as_of` cutoff.
- **UI-00006:** Playwright Chromium checks for desktop and 390px/320px layouts, page overflow, section navigation, keyboard skip, reduced motion and page errors.
- **UI-00007:** browser-level analytics refresh and paginated CSV download. The test simulates a 500-row YouTube page, a keyset-cursor second page and one TikTok page; the actual Chromium download must contain 502 data rows.

Desktop and compact-mobile full-page screenshots are captured after analytics fixture data loads and uploaded as the `nexus-dashboard-browser-screenshots` Actions artifact.

### Core latest work

- **BUILD-00336–00338:** fair, bounded TikTok metrics candidate selection; ordered publication index; correlated latest-snapshot lookup; EXPLAIN QUERY PLAN regression.
- **BUILD-00339:** TikTok collector OAuth initialization and lease-fencing tests.
- **BUILD-00340:** synthetic 10,000-publication / 10,000-snapshot candidate-scan smoke test.
- **BUILD-00341–00344:** Docker Compose service integration, AES-256-GCM backup creation, isolated restore, and wrong-key fail-closed verification.

## Validation evidence

### Core

- Backend validation [run 44500547468](https://github.com/justinhblee-prog/shorts/actions/runs/44500547468): **712 tests passed**.
- Compose recovery [run 44500547381](https://github.com/justinhblee-prog/shorts/actions/runs/44500547381): five services start, API readiness HTTP 200, encrypted backup archive created, plaintext archive absent, wrong-key restore rejected without changing the target DB, correct-key restore succeeded and SQLite integrity passed.
- Synthetic 10k-row due scan measured 0.65 ms on the GitHub Actions runner. This is not a production latency SLA.

### UI

- Latest synchronized UI head `5e86a432f7bdc42280d1293d3a52fa70eb95b057` passed [Actions run 44501015943](https://github.com/justinhblee-prog/shorts/actions/runs/44501015943): **717 tests** plus Playwright Chromium.
- Browser checks passed at desktop, 390px and 320px widths; keyboard navigation, reduced-motion behavior, analytics busy/as-of state and paginated 502-row CSV download all passed.
- The same head passed Compose integration [run 44501015973](https://github.com/justinhblee-prog/shorts/actions/runs/44501015973).
- Populated desktop/mobile screenshots are in artifact [14516529812](https://github.com/justinhblee-prog/shorts/actions/runs/44501015943), available until 2027-02-17.

## Remaining integration and external validation

- Connect the UI to the real authenticated API and validate full create → review → approve → publish → analytics flows.
- Verify actual YouTube/TikTok OAuth, publishing, analytics collection and provider error recovery with authorized accounts.
- Verify real browser download against live backend data, not only deterministic API fixtures.
- Validate on physical touch devices and with assistive technologies.
- Deploy on the intended production host with HTTPS, persistent volumes, secret rotation, monitoring and alerts.
- Perform a production-data/off-host backup and disaster-recovery drill; CI uses synthetic disposable data and an ephemeral key.
- Validate actual media quality, platform policy, costs and cohort ROI.

The eight mandatory launch gates remain at **1/8**. CI and synthetic fixtures do not satisfy external, deployment or business-evidence gates.


### UI-00008 — resilient partial dashboard refresh

- Replace all-or-nothing dashboard refresh handling with per-workspace `Promise.allSettled` results.
- Keep successful module data available when an unrelated API endpoint fails; report the number and names of failed modules in the connection indicator and toast.
- Distinguish full connection failure from partial API availability rather than marking every workspace disconnected after one endpoint error.
- Source regression coverage added. Browser test with intentionally mixed endpoint responses remains to be added.
