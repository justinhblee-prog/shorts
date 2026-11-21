# NEXUS STUDIO PRO — UI Visual Direction v0.2

## Approved visual direction

The dashboard must not retain the earlier cyan/blue operations-console appearance. The agreed direction is a deep navy / near-black canvas with violet and purple as the primary brand accent.

- Base canvas: near-black navy with restrained violet atmospheric gradients.
- Primary accent: violet/purple gradients, luminous but controlled; no cyan as the dominant accent.
- Navigation: persistent left rail on desktop, compact icon rail on mobile.
- Surfaces: layered dark panels, subtle purple borders, soft depth and shadows, rounded cards.
- Dashboard: retain the existing operational information architecture (KPI row, studio workflow, intelligence, review queue, operations/revenue) while strengthening visual hierarchy.
- Hero: retain and reveal the orbital content-engine visual, with violet glow and restrained motion; respect reduced-motion preferences.
- Controls: dark fields with violet focus rings; primary actions use violet gradients.
- Functional behavior, API wiring, IDs, form semantics and review/publishing safety gates must remain unchanged.

## Implementation note

The cyber-magic.css dashboard composition existed but was not linked from index.html. The initial preview therefore loaded only styles.css and preserved the earlier horizontal cyan-accented landing page. This refresh links the dashboard layer after the base stylesheet and overrides its prior blue/cyan palette with the approved violet system.

## Validation

The responsive Playwright smoke asserts that the dashboard stylesheet is loaded, the violet design token is active, the desktop sidebar is fixed at the intended width, the hero visual is visible, and primary actions use the new gradient. Existing desktop/tablet/mobile/landscape/320px overflow checks remain in place.

This is a preview-only visual change. No production deployment, merge, publishing or backend behavior is changed.


## Command-center and media-preview increment

The overview now exposes queue/review counts, worker count and pause state from the existing authenticated API refresh, saved market signals, and measured view-delta/Analytics coverage context. The review queue embeds a native video player only when a validated HTTPS video artifact URL is present; otherwise it clearly shows an empty preview state. The command-center safety sequence is explanatory and does not bypass or replace the existing policy, quality, human-approval, or private-upload gates.

Validation is extended to assert the overview composition, four trust-gate steps, market signal container, and single-column mobile layout. Media preview playback still requires a real authenticated review item and supported browser codec; fixture/empty-state UI checks do not claim live media playback.


## Studio workbench information architecture — 2026-11-21

The dashboard now has a distinct studio-floor layer between the live command center and the production form. It makes the core content-production workflow the visual center rather than treating the page as a stack of generic operations cards:

- A four-stage production timeline (discover, create, review, measure) derives counts from the existing page's authenticated API-backed queue, review, trend and approved-content views. Unknown values remain unavailable; the UI does not fabricate metrics.
- A media spotlight mirrors the first available validated review video artifact. It remains an explicit empty state when no real review video exists.
- A persistent work-queue rail repeats the live queued/running/review counts and surfaces the existing human-approval boundary.
- A global keyboard-accessible search (Ctrl/Cmd+K) searches visible work items and navigates to the matching content without adding another API or changing backend permissions.
- The new layout is responsive: three-column desktop, two-column tablet and single-column mobile.

The new interaction layer is presentation/navigation only. Existing production, review, queue-control, OAuth, finance and private-upload endpoints and their authorization checks remain authoritative. Preview validation must cover the new workbench, search entry point, four timeline stages and responsive overflow. A video is not claimed to be playable unless a real artifact URL and browser-supported codec are present.


## Workspace-aware studio floor and EDL editor — 2026-11-21

The fixed left navigation, workspace selector and global keyboard search remain the primary shell. The production floor is placed immediately after the operating KPIs and gives Discover/Create/Review/Measure a single visual route, while the existing local timeline remains the source-preview/editing surface. Server render controls are visually subordinate to the timeline and clearly distinguish private upload, server render, review-pending artifact and human decision. The artifact preview stays private; approval is not publication.


## Media bin and visual timeline — 2026-11-21

The editing workspace now follows a three-zone arrangement: a searchable local media bin with vertical video thumbnails, a central source/server preview, and a right-side clip sequence plus detail inspector. A full-width timeline below uses a ruler and distinct video, title-overlay and audio-bed lanes. Shelf cards and timeline segments share the same clip selection state. The design preserves the existing left navigation, workspace context, violet palette and human-review boundary.
