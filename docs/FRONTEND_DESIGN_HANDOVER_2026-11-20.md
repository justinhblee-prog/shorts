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
