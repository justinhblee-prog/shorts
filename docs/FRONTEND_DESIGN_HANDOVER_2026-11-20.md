# NEXUS STUDIO PRO — Frontend Design Handover
Date: 2026-11-20
Version: 0.11.0
Branch: `ui/nexus-premium-visual-refresh-2026-11-20`
PR: #417 (Draft / Open / Unmerged)

## Approved visual reference

Use the Library reference **`넥서스 스튜디오 프로 AI 대시보드(1).png`**, created 2026-11-19 16:08 KST, as the dashboard visual target. It depicts the NEXUS STUDIO PRO AI short-form content workspace, not a generic teal operations dashboard and not the older public landing page.

The target composition:
- Dark, premium purple / indigo / blue neon interface with restrained glass panels and glowing accents.
- Fixed left sidebar with the NEXUS STUDIO PRO identity, Korean navigation, Pro workspace card and version label.
- Top workspace toolbar with global workspace selector, command search (Ctrl+K), notifications, profile, date range and primary create action.
- Main dashboard hero with the Korean heading **콘텐츠 운영 대시보드**, a cinematic space/planet visual and a clear new-project CTA.
- Four KPI cards, using real API values only (never copy illustrative numbers from the mockup into live metrics).
- Existing content calendar, review queue, production pipeline, trend intelligence, analytics and operations modules remain connected to their current APIs.

The broader 9-screen UI showcase is a product-wide reference; this PR implements the approved dashboard shell and does not claim every future page is complete.

## Current implementation

- `frontend/index.html`: sidebar navigation, workspace toolbar, dashboard heading and primary CTA.
- `frontend/nexus-approved-design.css`: dedicated purple/blue visual system, desktop sidebar, responsive mobile navigation, KPI/panel styling and hero space visual.
- `frontend/styles.css`: removed the Google Fonts network import; local-first font stack is defined in the approved design layer.
- Korean font priority: Pretendard Variable → Pretendard → Noto Sans KR → Apple SD Gothic Neo → Malgun Gothic → system UI.
- `frontend/app.js`: keyboard search shortcut Ctrl+K, Enter-to-navigate matching dashboard headings, Esc-to-clear, and settings navigation.
- Existing API-backed metrics, review approval, analytics history/export, trend discovery, schedules and finance controls retain their original DOM IDs and application behavior.

## Navigation mapping

The visual sidebar exposes the reference's ten Korean destinations:
1. 대시보드
2. 트렌드 탐색
3. 콘텐츠 기획
4. AI 제작
5. 영상 편집
6. 검수·정책
7. 게시 관리
8. 성과 분석
9. 작업 관리
10. 설정

Some entries intentionally land on the same existing feature section until dedicated route-level screens are implemented. In particular, 영상 편집 currently opens the production workspace; it is not evidence of a standalone timeline editor.

## QA gates

- Backend static tests must retain the existing accessible navigation contracts and Korean localized tooltips.
- Chromium smoke must verify: the approved 9 anchor destinations plus settings control; keyboard search; settings dialog; authenticated real API content; no U+FFFD replacement glyphs after API data loads; responsive layout at 390px and 320px; every sidebar touch target at least 48px; keyboard skip navigation; approval audit; analytics pagination and CSV export; partial API failure feedback.
- Screenshots are candidate evidence only until exact-head Chromium smoke passes.
- No external Google font request is required for Korean readability.
- Do not claim the dashboard visual is accepted until the user reviews the actual latest browser screenshot artifact.

## Remaining

- Exact-head Chromium smoke and fresh desktop/mobile screenshot artifact after the latest CSS/HTML changes.
- Inspect the screenshot against the 2026-11-19 reference; refine hero composition, information density and spacing based on actual browser output.
- Dedicated editor route/workspace is not yet implemented; do not label the current production form as a finished video editor.
- Full multi-page route-level implementation and real user account/brand configuration remain separate product work.

## Safety

PR #417 remains Draft/open/unmerged. No merge, deployment, secret change, runner configuration change, workflow dispatch or live provider action was performed.

- Global search now scans visible live task/review/calendar/analytics rows as well as section headings and form labels; the browser smoke verifies Ctrl+K and an authenticated review-task result.
- Browser smoke also checks that the approved design token stylesheet is loaded, the desktop sidebar/main offset is 258px, the violet design token is present, and no Google Fonts network requests occur.


## Exact-head QA evidence — 2026-11-20

- Verified code head: `2c351e3f0696333435227a2fd1bb9de92ddf4fe0`.
- CI: [run 44668155728](https://github.com/justinhblee-prog/shorts/actions/runs/44668155728) passed **736 backend tests**, frontend syntax, and Chromium desktop/mobile smoke.
- Browser checks confirmed Korean text rendering with zero replacement glyphs, approved navigation, keyboard search against authenticated review content, settings entry, authenticated review approval/audit history, analytics pagination and CSV export, partial API failure handling, and reduced-motion behavior.
- Fresh visual artifact: [14599326297](https://github.com/justinhblee-prog/shorts/actions/runs/44668155728/artifacts/14599326297) (6 MB). Compose integration smoke also passed [44668155732](https://github.com/justinhblee-prog/shorts/actions/runs/44668155732).
- This is a QA-verified candidate, not yet accepted by the user. PR #417 remains Draft/open/unmerged.


## Feature navigation follow-up — 2026-11-20

- Sidebar destinations now resolve to distinct existing feature surfaces rather than sending several labels to the same section: trend collection, editorial recommendations, production request, production pipeline, review queue, publishing overview, analytics history and task queue.
- Anchor scroll margins preserve the sticky workspace toolbar. Browser smoke now asserts all nine destinations exist, the links point to the correct targets, and URL/active-state updates occur after navigation clicks.
- Exact-head CI is running on `2e6ba4f2d7e1495c45c626f3c24c56fd07652fc0`. The production pipeline anchor is not represented as a dedicated nonlinear video timeline editor.


## Local timeline editor milestone — 2026-11-20

- Added a dedicated timeline workspace under the production pipeline: local video import, browser preview, ordered video/title clips, clip selection, non-destructive in/out trim values, clip reordering/removal, and edit-decision-list JSON export.
- The editor is local/browser-only and does not upload source media to the backend. JSON export explicitly records `rendered: false`; MP4 rendering, audio mixing, transitions, captions burn-in, and server-side render jobs remain unimplemented pending a rendering engine integration.
- Browser smoke now exercises title clip creation, selection, removal, and empty-state recovery. Exact-head CI is running on the latest UI branch commit.
- Removed the apt package-manager dependency from hosted UI validation. Korean text is still checked in Chromium; the browser uses installed OS fallback fonts rather than waiting on network package installation.

- Follow-up CI correction: navigation browser assertions now exercise the new distinct feature anchors instead of legacy section anchors; legacy assertion caused a stale selector timeout and did not indicate a UI runtime failure.


## Expanded timeline interaction verification — 2026-11-20

- Exact code head `c34bc061f887d66bb699961f337c572462ecd4cc` passed [run 44669819398](https://github.com/justinhblee-prog/shorts/actions/runs/44669819398): 736 backend tests, frontend syntax, Chromium desktop/mobile, Korean glyph checks, authenticated review/analytics workflows and timeline interaction coverage.
- Timeline checks verify two title clips, selection, reorder, in/out trim values, downloaded JSON EDL structure (`rendered: false`), deletion and empty-state recovery.
- Fresh browser artifact: [14599428350](https://github.com/justinhblee-prog/shorts/actions/runs/44669819398/artifacts/14599428350). Compose integration smoke [44669819487](https://github.com/justinhblee-prog/shorts/actions/runs/44669819487) passed service startup/readiness and scheduled isolated backup/restore.


## Timeline preview refinement — 2026-11-20

- Added selected-range playback that seeks to the clip in-point and pauses at the out-point; trim changes are reflected in the preview boundary.
- Added total timeline duration, title overlay preview, media MIME/byte metadata in the EDL, non-video upload rejection, and a 512 MiB browser-side per-file guard / 20-clip cap.
- The timeline remains local-only and exports an EDL, not an MP4. See `docs/VIDEO_EDITOR_RENDER_INTEGRATION.md` for the secure asset-upload, EDL validation, restricted FFmpeg worker, review and retention architecture required before real rendering.


## Exact-head validation — selected-range preview and upload guards

- UI code/documentation head `003956e5509c16edf06caeedc865cdc3d90fff06` passed [Backend tests run 44670600009](https://github.com/justinhblee-prog/shorts/actions/runs/44670600009): **736 backend tests**, frontend syntax and Chromium desktop/mobile smoke. The smoke verified rejection of non-video uploads, title overlay preview, selected-range control, aggregate duration, EDL JSON structure/download, clip reorder/trim/removal, and existing authenticated review/analytics flows.
- Compose integration smoke passed [run 44670599939](https://github.com/justinhblee-prog/shorts/actions/runs/44670599939), including service readiness and scheduled isolated backup/restore.
- Fresh browser artifact: [14599966062](https://github.com/justinhblee-prog/shorts/actions/runs/44670600009/artifacts/14599966062) (5.39 MB).
- The local editor remains EDL-only; actual MP4 rendering is blocked on the asset-upload/ownership/EDL-render-worker work described in `docs/VIDEO_EDITOR_RENDER_INTEGRATION.md`.


## Title preview recovery regression — exact-head verification

- UI head `195391211f63b21651127d7cb56bef776d09a5c8` passed [Backend tests run 44670853201](https://github.com/justinhblee-prog/shorts/actions/runs/44670853201): **736 backend tests**, frontend syntax, Chromium desktop/mobile and authenticated application smoke.
- Added regression coverage for the selected title overlay remaining visible after removing another clip, and for overlay/empty-state cleanup after the last clip is removed. Object URLs are released when the editor page unloads.
- Compose integration smoke passed [run 44670853253](https://github.com/justinhblee-prog/shorts/actions/runs/44670853253).
- Latest browser artifact: [14600126059](https://github.com/justinhblee-prog/shorts/actions/runs/44670853201/artifacts/14600126059) (5.38 MB).
