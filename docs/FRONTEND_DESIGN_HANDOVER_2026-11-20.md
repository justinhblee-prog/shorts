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


## Vercel browser preview — 2026-11-20

- A standalone Vercel project `nexus-studio-pro-preview` was created in the user's `justinhblee-9540` team without connecting a Git repository, adding environment variables, or configuring automatic deployments.
- Canonical browser preview (Vercel deployment target: **preview**, state: **READY**): https://nexus-studio-pro-preview-9u0f9wjoc-justinhblee-9540.vercel.app
- Snapshot source: branch `ui/nexus-premium-visual-refresh-2026-11-20`, commit `f34348f6030221ca3e4c09857861d274f8948a77`.
- The preview includes the six static frontend files: `index.html`, `app.js`, `styles.css`, `cyber-magic.css`, `nexus-premium.css`, and `nexus-approved-design.css`.
- Project-level Vercel Authentication protection is enabled for **all** deployment targets. No custom domains are configured.
- This is a static UI snapshot, not a connected production stack: relative `/api/*` requests have no deployed FastAPI backend, and authenticated API-backed actions will not operate until a separately approved backend environment is connected.
- The project is intentionally not linked to Git; subsequent commits do not auto-deploy. Refresh the preview only after a new snapshot is explicitly built from a verified branch/commit.
- Vercel also registered an initial protected production-target bootstrap deployment during project initialization. It has no custom domain and is covered by the same project-wide Vercel Authentication protection. **Do not use it as the review URL**; the preview URL above is the intended review target.
- No production repository, main branch, secrets, or existing Vercel project was modified.


## Exact-head verification — workspace DB path and EDL validation hardening (2026-11-20)

- Current PR head: `9ebc36e4b692a70d51c5ab6a4ef1709578b6b54c`.
- Fixed `WorkspaceStore` default database resolution to honor `NEXUS_DB_PATH` (falling back to `data/nexus.sqlite3`), matching the API, worker and scheduler. Explicit test database paths still take precedence. Added regression tests for both configuration paths.
- Hardened EDL v1 validation: boolean values are no longer accepted as integer schema versions, and integer-to-float overflow is converted into a controlled validation error rather than an unhandled exception. Added regression cases and updated the render integration design record.
- Exact-head backend validation and Chromium desktop/mobile smoke passed: [run 44674295290](https://github.com/justinhblee-prog/shorts/actions/runs/44674295290). Browser artifact: [14602255338](https://github.com/justinhblee-prog/shorts/actions/runs/44674295290/artifacts/14602255338) (5.37 MB).
- Exact-head Compose integration passed: [run 44674295302](https://github.com/justinhblee-prog/shorts/actions/runs/44674295302), including service startup/readiness and scheduled backup/isolated restore.
- Workspace registry remains a standalone persistence module; FastAPI identity integration and migration from operator workspace configuration are still gated on a trusted end-user principal source. No upload or MP4 render endpoint is claimed.
- PR #417 remains Draft/open/unmerged.

 
## Authenticated operator workspace API — 2026-11-20

- Added token-derived operator workspace creation/listing and workspace member add/revoke endpoints under `/api/operator/workspaces`.
- Caller identity is always resolved from the review token. Workspace creation rejects extra fields, so a caller cannot supply `owner_principal_id`; member principal IDs are only the target of a membership action.
- All mutations require `media.manage` plus owner/admin membership in the target workspace. Listing is scoped to the authenticated principal.
- Added explicit EDL authorization modes: `legacy_config` remains the compatibility default; `sqlite` uses only durable workspace membership and does not fall back to legacy JSON grants. Unknown modes fail closed.
- Added FastAPI TestClient coverage for token-derived ownership, authenticated listing, member role enforcement, unauthenticated access, and SQLite-mode cross-workspace denial even when the legacy config would grant access.
- Current principal type is still a configured operator identity, not a customer account. No production auth-mode switch, customer identity integration, migration, asset upload, or MP4 rendering is enabled.
- Exact-head CI for this implementation: [Backend tests run 44675134276](https://github.com/justinhblee-prog/shorts/actions/runs/44675134276); [Compose integration run 44675134115](https://github.com/justinhblee-prog/shorts/actions/runs/44675134115).

 
## Workspace API validation correction — 2026-11-20

- The first API-test attempt exposed that this repository's pinned Starlette environment requires `httpx2` for `TestClient`, which is not a declared project dependency. Tests were changed to call the FastAPI route functions directly with isolated auth/store patches; no new runtime dependency was introduced.
- Corrected the revoked-membership test to revoke a non-owner member, preserving the invariant that the last owner cannot be removed.
- Added explicit RBAC protection to the operator workspace list endpoint.
- Revalidation is required on the corrected branch head; the earlier backend run failed on the initial test harness and must not be counted as a passing result.

 
## Workspace membership and audit read APIs — 2026-11-20

- Added `GET /api/operator/workspaces/{workspace_id}/members`; only an active workspace member with `media.manage` operator permission can view active membership.
- Added `GET /api/operator/workspaces/{workspace_id}/audit`; only workspace owners/admins with `media.manage` can read immutable audit events. Pagination is bounded to 1–100 rows and a maximum offset of 1,000,000.
- API tests cover viewer/member read boundaries and owner/admin-only audit visibility.
- Latest implementation is being revalidated after these additions; prior green run 44675317760 covers the earlier API code revision, not these final additions.

- Principal identifiers are now rejected when they contain ASCII control characters; the first CI attempt caught a multiline conditional syntax typo, which was corrected in commit `b7efea5629c3fcf4f8f7cbca7c0fefe75e7d176f`. The corrected code and actual newline regression test passed in [Backend tests run 44675851438](https://github.com/justinhblee-prog/shorts/actions/runs/44675851438), with 766 tests total; [Compose integration run 44675851532](https://github.com/justinhblee-prog/shorts/actions/runs/44675851532) also passed.


## Final verification for operator workspace API — 2026-11-20

- Exact tested code snapshot includes the member/audit read APIs and control-character principal validation.
- Backend: [run 44675851438](https://github.com/justinhblee-prog/shorts/actions/runs/44675851438) — 766 tests passed; compile, frontend checks and Chromium desktop/mobile smoke passed.
- Compose: [run 44675851532](https://github.com/justinhblee-prog/shorts/actions/runs/44675851532) — service image build, process/readiness checks and cleanup passed.
- Test coverage includes workspace creation ownership spoofing rejection, member-scoped listing, membership administration, audit visibility, SQLite EDL cross-tenant denial, and principal control-character validation.
- Production remains on legacy workspace config mode by default; no environment setting or production deployment was changed.


## Tenant data isolation audit — 2026-11-20

- Completed source-schema inventory across queue, production, review/policy, brand profiles, scheduling, YouTube/TikTok publishing and OAuth, finance/intelligence, and media staging.
- Confirmed that most tenant-owned records do not yet carry `workspace_id`; workspace membership on the EDL validator alone is not multi-tenant data isolation.
- Added `docs/TENANT_DATA_ISOLATION_AUDIT.md` with phased, additive migration and rollout gates. No existing data was changed or backfilled.
- Customer identity provider selection is an external security/service contract. No customer login provider was guessed, configured, or activated.

## Customer identity contract — 2026-11-20

- Added `docs/CUSTOMER_IDENTITY_CONTRACT.md` as the provider-neutral application contract for future customer login and workspace ownership.
- Canonical identity is the exact verified `issuer + subject` pair, mapped to an opaque internal principal. Email and display names are profile attributes, never identity keys.
- Defines token verification, explicit workspace membership, secure account linking/invitations, revocation, worker/resource tenant propagation, migration gates and cross-tenant test requirements.
- Existing reviewer/operator credentials remain a separate trust domain. The current SQLite workspace registry is not customer authentication and does not establish complete tenant isolation.
- Identity provider selection, login/recovery methods, data residency and contractual/security settings remain unresolved external decisions. No provider or live login integration was activated.
- Shared database path review: `backend/app.py` passes `NEXUS_DB_PATH` to `WorkspaceStore`; the store's no-argument constructor also honors `NEXUS_DB_PATH`. Existing tests cover both environment-based default selection and explicit-path precedence. No path mismatch was found; no code change was warranted.


## Workspace-scoped media staging hardening — 2026-11-20

- Added optional `workspace_id` support to `MediaStager.stage` and `staged_path`. Workspace directory names and job filenames are SHA-256-derived opaque values; temporary download files are created within the selected namespace.
- Workspace IDs are validated before DNS resolution or outbound artifact requests.
- Workspace-scoped cleanup fails closed: the current YouTube upload store is globally keyed by `job_id`, so a global upload confirmation cannot prove tenant ownership. No tenant media is deleted through that path until upload records support scoped reads.
- Added tests for same-job path separation, opaque namespace names, pre-network validation, and fail-closed cleanup.
- Initial backend CI on commit `fafd6cd97706333244588dbe15615800f99851b2` exposed a test failure because workspace validation was initially placed after the artifact fetch. This was corrected in commits `fd29bb5485935d2752b866e801a389044c7bb284` and `75fe913185aefe16896889838c55d5a65bcbcb21`; the latest correction moves validation ahead of DNS/fetch and requires scoped upload proof for cleanup.
- Revalidation on exact latest head `b3e0f1e64ac940347435f6194741da5a0315c5d9` is running: [Backend run 44679594027](https://github.com/justinhblee-prog/shorts/actions/runs/44679594027), [Compose run 44679594008](https://github.com/justinhblee-prog/shorts/actions/runs/44679594008). Do not count either as passed until completed.
- Important limitation: no authoritative workspace ID is yet propagated from production job creation through queue, worker, provider recovery, upload records, and asset authorization. Existing recovered-render adoption still uses the legacy media namespace. This slice is a storage primitive and safety gate, not complete tenant isolation.


## Queue workspace ownership foundation — 2026-11-20

- Added nullable `workspace_id` to `pipeline_jobs` with a non-destructive SQLite startup migration and a workspace/status/creation index.
- `JobQueue.enqueue(..., workspace_id=...)` persists explicit ownership; claimed job objects retain that field for worker handoff. Existing legacy jobs remain unassigned (`NULL`).
- Global idempotency keys fail closed when reused from another workspace, preventing a duplicate request from returning another workspace's job. The existing global uniqueness constraint remains pending a reviewed migration to composite workspace/key uniqueness.
- Regression tests cover queue-to-claim ownership continuity, cross-workspace idempotency rejection and invalid workspace values.
- This does **not** yet provide tenant API authorization, workspace-filtered claims, workspace-scoped job events, production records, provider attempts, review or publishing data. No customer identity is inferred from operator credentials or request-supplied IDs.


## Queue and production tenant-scope follow-up — 2026-11-20

- Queue claim/get/events now support explicit workspace filtering at the SQL boundary; mismatched reads return the same not-found response as unknown IDs. Legacy unscoped calls remain for operator compatibility and are not customer authorization.
- Production runs persist nullable `workspace_id`, inherited from the matching durable production queue row at creation. Mismatched ownership on duplicate create is rejected.
- Regression coverage added for workspace-filtered claim, cross-workspace reads/events, invalid scope, production ownership inheritance and mismatch rejection.
- Authenticated workspace context is still not wired to API/worker routes. Do not treat request-provided workspace IDs as trusted identity; provider attempts, reconciliation and event ownership still need complete parent-scope enforcement.


- Follow-up: heartbeat, finish and fail queue transitions now accept an optional workspace scope and reject lease operations when the persisted job belongs to a different workspace. Regression tests verify rejected cross-workspace transitions do not change the running job, while the correct workspace can complete it.


- Provider journal follow-up: provider execution attempts and provider reconciliation audit rows now persist nullable workspace ownership inherited from their `production_runs` parent. Existing rows are backfilled; insert triggers derive ownership from the parent rather than request data. `provider_attempts()` now returns the persisted workspace field. Regression tests cover tenant inheritance and preservation of legacy unassigned records.


- Production API workspace scoping: production job creation, production detail and provider-attempt read endpoints accept `X-Nexus-Workspace-Id`. The value is resolved against the authenticated operator's configured or durable workspace membership, never trusted directly. Create persists the resolved workspace on the queue parent; production/provider journal reads apply SQL workspace filters. Omitting the header intentionally preserves legacy global operator access. This is an operator-console isolation capability, not customer identity/authentication or complete B2B tenant isolation.

- Additional API coverage: `/api/jobs/{id}`, `/api/jobs/{id}/events`, and production reconciliation-event reads accept the same optional workspace selector and resolve it through authenticated operator membership before querying. Immutable queue events expose parent workspace ownership via a join, avoiding duplicated mutable tenant fields in the audit log.


## 2026-11-20 exact-head validation and security follow-up

- PR #417 head `7a749a6b20b3d858cb57085a2e1231db89d57e04` passed Backend tests (run 44681380757) and Compose integration (run 44681381054). The backend workflow includes the Chromium dashboard smoke and uploaded browser screenshots artifact 14605210220.
- Tenant isolation remains partial: production detail/provider reads, production execution, and recovered-render adoption now resolve operator workspace membership and apply scoped parent/child reads; recovered media staging also uses the resolved workspace namespace. This is operator-only authorization, not a customer or independently authenticated worker boundary.
- Trusted worker identity-to-workspace binding and customer identity are not implemented. Never treat body/header workspace IDs, worker_id, or lease tokens alone as customer authorization. Keep these items open and preserve Draft PR status.
NaN now require authenticated operator workspace resolution for tenant-owned production jobs. Staging reads the parent in workspace scope and writes into the opaque workspace media namespace.
- `ProductionStore.artifact` and `ProductionStore.stage` accept optional workspace fences and verify parent ownership transactionally. API passes the verified scope when recording staged-media metadata and review transition.
- Tenant cleanup remains deliberately blocked until YouTube upload records support workspace-scoped reads; global job-ID lookup cannot authorize deletion of a tenant file.
- New tests cover workspace mismatch, missing selector, valid staging, fail-closed cleanup, and scoped store writes. Full backend/Compose/Chromium CI is running for the updated head.


### Trusted worker boundary contract — 2026-11-20

- Added `docs/WORKER_IDENTITY_CONTRACT.md` describing independent high-entropy worker credentials (hash-only config), immutable worker identity, explicit workspace grants, process-generation fencing, workspace-scoped claim/lease operations, revocation, audit, and acceptance tests.
- This is a design contract only. The existing direct-SQLite worker and operator-authenticated legacy HTTP job endpoints have not been silently reclassified as independently authenticated workers. No worker secret, environment setting, runner, or production execution path was activated.


### Exact-head validation — media lifecycle and tenant scope

- Code/test head `f8170009c8f1b959039b21816273d468801a1b0e` passed [Backend tests + Chromium browser smoke, run 44686718970](https://github.com/justinhblee-prog/shorts/actions/runs/44686718970).
- Compose integration passed [run 44686719048](https://github.com/justinhblee-prog/shorts/actions/runs/44686719048), including service readiness and isolated backup/restore.
- Fresh browser capture: [artifact 14607235689](https://github.com/justinhblee-prog/shorts/actions/runs/44686718970/artifacts/14607235689).
- Current branch head is documentation-only after the validated code/test head; PR #417 remains Draft/Open/Unmerged.


### Default-deny for omitted tenant read scope — 2026-11-20

- Production detail/provider-attempt reads and queue job/event reads now deny workspace-owned records if no workspace selector is supplied; a selector is resolved against the authenticated operator's membership first.
- Regression tests cover omitted selector (403), mismatched membership (403), and valid workspace scope. This closes the legacy global-read fallback for these job-level endpoints only; other resource families remain under audit.


## Review workflow workspace scope — 2026-11-20

- Review inbox, approved queue, and publishing overview now resolve `X-Nexus-Workspace-Id` through authenticated operator membership before reading review rows.
- Review decisions and policy-evidence changes are workspace-fenced in the store transaction; omitted scope can see/act only on legacy unassigned rows.
- Regression coverage verifies workspace A cannot list, decide, or alter policy evidence for workspace B's review job, while a matching workspace can complete the review.
- Code head `7dc2b1742256832a744810188fdff1638668e6d7` passed Backend tests and Chromium browser smoke (run `44687938486`) plus Compose integration build/readiness/backup/restore (run `44687938515`).


## Scheduled production workspace scope — 2026-11-20

- Schedule records are now workspace-owned; existing records migrate as legacy unassigned (`workspace_id = NULL`).
- Schedule creation, listing, activation, outbox status, and dead-letter retry use the authenticated operator's resolved workspace scope.
- Due dispatch propagates the schedule's workspace ID into the durable queue job; outbox rows inherit scope from their parent schedule.
- Regression coverage covers workspace A/B schedule isolation, dispatch propagation, and preservation of legacy orphan outbox records. Code head `effc7a497b9c64b2fbcef1b8d1b7bb3c004f5117` passed Backend tests + Chromium browser smoke (run `44688516667`) and Compose integration build/readiness/backup/restore (run `44688516822`).

## Additional workspace isolation — publishing, analytics, finance, opportunities

- Publishing job endpoints verify the authenticated workspace against the immutable production parent before reading or mutating YouTube/TikTok publication records.
- YouTube video analytics routes resolve video ownership through the upload record and enforce the same workspace check. Analytics history uses publication-to-production joins and workspace filtering.
- Financial ledger and scored opportunity records now persist nullable workspace ownership. Finance writes with a job ID must match its production parent; finance reports and opportunity lists are workspace-scoped. Legacy rows stay in the unassigned NULL namespace.
- Public trend signals and default brand profiles are treated as shared platform reference data; generated production work retains workspace ownership.
- Latest code head e092f8013fa07b66c355bc7fee51a21cb4b1377f passed Backend/Chromium run 44694735250 and Compose integration run 44694735235.

## Worker identity API slice — 2026-11-20

- Added opt-in SHA-256 digest-based worker authentication in backend/worker_auth.py. Worker identity and explicit workspace grants come only from NEXUS_WORKER_CREDENTIALS_JSON; no plaintext credential is stored in source.
- Added /api/worker/v1/register, /claim, and per-job /heartbeat, /complete, /fail endpoints. The API derives workspace ownership from queue rows, filters claims by the worker's allow-list, and requires a server-issued process-generation token for lease mutations.
- Legacy operator-token worker endpoints are rejected with HTTP 410 once worker credential mode is configured. With no worker credential configuration, legacy compatibility remains unchanged.
- The existing worker process still accesses SQLite directly and has not been migrated to this API. The new protocol is not a claim of full worker isolation; no credentials, runner settings, or production execution were activated.
- Added unit and API tests for digest validation, explicit grants, workspace-fenced claim/lease behavior, legacy-mode guard, and stale process-generation rejection. Code head aa2fa5b96205323fa97e58e9fbda89c0a6199f68 passed Backend validation + Chromium browser smoke (run 44692285597) and Compose integration smoke (run 44692285539).

## Active workspace selection and scoped performance evidence — 2026-11-20

- Added a responsive workspace selector to the dashboard toolbar. It loads only the authenticated operator's memberships and sends X-Nexus-Workspace-Id on subsequent API calls when selected. No workspace is auto-selected; the default view remains unassigned legacy data.
- Workspace metadata listing uses a dedicated workspace.read permission; creating or managing memberships retains stronger media.manage permissions.
- Performance insights and recommendation exposure/evaluation now use workspace-scoped production and financial evidence. Recommendation selections are linked only when the production job and exposure share the same workspace.
- Browser smoke verifies membership loading, workspace selection header propagation, and return to the legacy default. Latest code head e092f8013fa07b66c355bc7fee51a21cb4b1377f passed Backend/Chromium (run 44694735250) and Compose integration (run 44694735235).

## Queue workspace boundary refinement — 2026-11-20

- Queue statistics and ambiguous reconciliation lists are workspace-filtered. Queue retry and cancel actions verify the job's workspace before mutation.
- Generic enqueue stamps the authenticated workspace. Legacy operator-token worker routes are workspace-filtered and restricted to unassigned legacy jobs when no workspace is selected; the new worker v1 credential API remains the preferred opt-in path.
- System-level queue pause/resume/recovery and worker registry remain privileged global operations.
- Regression tests added for workspace queue counts and cross-workspace cancellation denial. Latest code head e092f8013fa07b66c355bc7fee51a21cb4b1377f passed Backend/Chromium (run 44694735250) and Compose integration (run 44694735235).

## Explicit remaining multi-tenant integrations

- YouTube/TikTok OAuth credentials and creator identity remain global service connections, even though publication jobs and metric histories now enforce workspace ownership. Per-workspace encrypted provider credentials and workspace-bound OAuth flows remain a separate required milestone; no external credentials were configured.
- Customer OIDC login/identity is not implemented. The workspace selector uses authenticated operator membership only.
- The worker process still uses direct SQLite; the new opt-in worker API is not yet consumed by the worker runtime.
- Tenant asset registry/retrieval and workspace-owned custom brand profiles remain future work. Existing default brand profiles and public trend/competitor signals are shared platform references.


- Workspace provider-connection architecture and migration requirements are specified in docs/WORKSPACE_PROVIDER_CONNECTION_CONTRACT.md. Implementation is intentionally blocked on provider account cardinality, approved KMS/key vault, OAuth app ownership, and authorized first tenant; no credentials or external connection were activated.
