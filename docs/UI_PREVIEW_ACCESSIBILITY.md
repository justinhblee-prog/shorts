# Visual preview accessibility and mobile QA

## Purpose

The isolated NEXUS visual preview is a read-only review surface. It is not an authenticated production workspace and must not submit production, publishing, scheduling, credential, or finance actions.

## Accessibility behavior

- The fixed preview banner uses a polite, atomic status announcement and hides its decorative pulse from assistive technology.
- The connection state announces that the preview is disconnected from operational APIs.
- The floating feedback control has a stable accessible name, `aria-controls`, and an explicit `aria-expanded` state.
- Opening the feedback panel moves focus to its labelled text field. Escape closes the panel and restores focus to the toggle.
- Copy success and clipboard-denied fallback are announced through a polite status region. The fallback selects the complete feedback text for manual copying.
- Keyboard focus is visibly outlined. Reduced-motion preferences are respected.

## Mobile behavior

The preview banner and floating feedback panel are checked at 390px and 320px viewport widths. Feedback controls maintain touch-sized targets and remain within the viewport; the smoke asserts there is no document-level horizontal overflow.

## Deterministic browser smoke

Run from the repository root after installing the backend requirements and Playwright Chromium:

```sh
python -m pip install -r backend/requirements.txt
npm install --no-save playwright@1.56.1
npx playwright install chromium
node scripts/ui_preview_accessibility_smoke.mjs
```

The smoke starts the disposable local UI API fixture server, requests the actual dashboard and served `/assets/preview-mode.js`, then activates the same read-only preview overlay using the CI-only query switch `?nexus-preview-test=1`. It blocks API calls, injects a denied clipboard write to exercise the fallback, and checks keyboard focus, open/close, Escape restoration, 390px/320px layout, disabled operational actions, and absence of mutating API requests.

The query switch only activates the safe visual-preview overlay; it does not enable operational actions. The deployed preview remains scoped to its dedicated `nexus-studio-pro-ui-preview*.vercel.app` hostname.

## Validation evidence

Executable code head `d9088036e8903d3ddb5253cc3a176a20ee6b3450` passed GitHub Actions run [44909218455](https://github.com/justinhblee-prog/shorts/actions/runs/44909218455):

- `sh scripts/validate.sh`: 809 tests passed.
- `node scripts/ui_browser_smoke.mjs`: passed, including desktop/mobile, keyboard, review, analytics pagination and reduced-motion checks.
- `node scripts/ui_preview_accessibility_smoke.mjs`: passed keyboard navigation, feedback focus and Escape behavior, clipboard fallback, 390px/320px viewport checks, and read-only API guard.
- Workflow completed successfully and uploaded the existing dashboard browser screenshot artifact.

No Vercel deployment, public publishing, production API action, or merge was performed. Draft PR #457 remains open for review.
