# BUILD-00001 — Durable queue and Worker Lease

Python 3.11+ recommended.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
uvicorn app:app --host 0.0.0.0 --port 8502
```

Set `NEXUS_DB_PATH` and `NEXUS_LEASE_SECONDS` as needed. SQLite uses WAL, foreign keys, busy timeout, serialized claims, unique idempotency keys and lease fencing tokens.

API: POST /api/jobs, POST /api/jobs/claim, POST /api/jobs/{id}/heartbeat, POST /api/jobs/{id}/complete, POST /api/jobs/{id}/fail, GET /api/jobs/{id}, GET /api/jobs/{id}/events, GET /api/queue/stats.

Successful generation transitions to `review_pending`, never directly to public publishing. This milestone does not yet include production worker processes, PostgreSQL, OAuth, rendering, or platform publishing.


## Global trend and competitor intelligence

Trend ingestion:
- `POST /api/trends/collect` with JSON such as `{"region":"US","query":"AI tools","limit":20,"include_hacker_news":true}`
- `GET /api/trends?region=US&limit=50`
- Regions: KR, US, JP, GB. Google News RSS does not provide search volume or YouTube view counts; unavailable metrics are null.

Competitor intelligence:
- Set `YOUTUBE_DATA_API_KEY` in the backend environment.
- `GET /api/competitors/search?q=fitness&limit=5`
- `GET /api/competitors/{channel_id}?video_limit=10`
- `GET /api/competitors`
- YouTube Data API search requests consume quota (search.list is typically 100 units); prefer direct channel IDs when known and avoid aggressive polling.
- Subscriber/view/video counts are provider snapshots, not growth rates, RPM or revenue.


## Profitability scoring (scenario estimates)

- `POST /api/opportunities/score` accepts low/high view forecasts, RPM assumptions, cost ranges, optional affiliate/sponsor assumptions, monetization eligibility and evidence/fit/feasibility scores.
- `GET /api/opportunities` lists saved scenarios by priority score.
- A non-empty `forecast_source` is required. Results are explicitly labeled `estimate`; they are not actual earnings or guaranteed results. If monetization is not eligible, ad revenue is forced to zero.
- The prioritization score is explainable: margin 35%, ROI 25%, evidence quality 20%, strategic fit 10%, production feasibility 10%.


## BUILD-00005 — short-video production pipeline

The provider-agnostic orchestration layer is in `production_pipeline.py`.
It submits durable `short_video_production` queue jobs and executes three
configured provider stages in order: script, voice generation, and 9:16 video
rendering. Provider URLs and optional bearer tokens are read from the runtime
environment:

- `SCRIPT_PROVIDER_URL`, `SCRIPT_PROVIDER_TOKEN`
- `VOICE_PROVIDER_URL`, `VOICE_PROVIDER_TOKEN`
- `RENDER_PROVIDER_URL`, `RENDER_PROVIDER_TOKEN`

Each provider accepts a JSON POST contract. Script providers must return a
non-empty `script`; voice providers must return an HTTP(S) `audio_url`;
renderers must return an HTTP(S) `video_url`. Provider-specific adapters can
map vendor APIs to this contract without coupling the core pipeline to one
vendor. Missing configuration or malformed output fails closed; no placeholder
audio/video or fabricated artifact URL is created.

API:
- `POST /api/production/jobs` — create a durable job; body: `brand`, `region`,
  `language`, `topic`, optional `idempotency_key`.
- Claim the job with `POST /api/jobs/claim`.
- `POST /api/production/jobs/{id}/execute` — execute only with the current
  `worker_id` and `lease_token`.
- `GET /api/production/jobs/{id}` — inspect stages and artifacts.
- `python worker.py` — run the long-lived worker. It claims only `short_video_production` jobs, renews its lease while provider calls run, and finalizes the queue into `review_pending` after successful rendering.

A completed render transitions the queue job to `review_pending`. This is not
a publish operation. Public publishing remains outside this pipeline and must
require explicit human approval. Provider contracts have mocked unit tests;
live provider compatibility, actual generation, artifact download/playback,
and render quality have not been validated.


## BUILD-00006 — ten-brand operations

`brand_operations.py` seeds and persists the ten operating brands. Each profile
defines its vertical, positioning, audience, tone, supported markets/languages,
risk level and editorial review rules. Defaults are inserted only when missing,
so operator activation settings survive restarts.

API:
- `GET /api/brands` — list all brands.
- `GET /api/brands?active_only=true` — list active brands only.
- `GET /api/brands/{slug}` — inspect a brand profile.
- `PUT /api/brands/{slug}/activation` with `{"active":false}` — pause or
  reactivate a brand.

Production job creation accepts a registered active brand name or slug and
rejects unsupported region/language combinations. Initial supported regions
are KR, US, JP and GB; supported languages are Korean, English and Japanese.

## BUILD-00007 — human review

Configure a strong `NEXUS_REVIEW_TOKEN` secret in the API environment. Review endpoints require it in the `X-Review-Token` header and fail closed if unset.

- `GET /api/review/pending`
- `POST /api/review/{job_id}/approve`
- `POST /api/review/{job_id}/reject`
- `POST /api/review/{job_id}/request-revision`
- `GET /api/review/{job_id}/history`

Request body: `{"reviewer_id":"operator-1","comment":"Optional approval note"}`. Rejection and revision requests require a comment. Decisions record the reviewed artifact snapshot and are append-only; a decision cannot be overwritten. Approval does not trigger upload or public publishing. The current reviewer ID is asserted by the caller; integrate a real identity provider and role-based authorization before multi-user production deployment.

## BUILD-00008 — YouTube private publishing and counters

Configure `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` as runtime secrets. The refresh token must be granted `youtube.upload` and `youtube.readonly` scopes. Never commit credentials or token files.

The upload endpoint requires the configured `NEXUS_REVIEW_TOKEN` in `X-Review-Token` and a job with a recorded `approved` human decision:
- `POST /api/youtube/upload/{job_id}`
- `GET /api/youtube/uploads/{job_id}`
- `POST /api/youtube/videos/{video_id}/refresh-metrics`

Upload body includes a server-local `media_path`, title, description, tags and category ID. The API forces `privacyStatus=private`; there is no public/unlisted override. The server must already have the rendered file at that local path. Current render providers return artifact URLs, so downloading/staging remote artifacts into trusted local storage is a separate deployment integration and is not silently performed by this endpoint.

Uploads use the Google API client resumable media upload interface. The upload record and source-provided view/like/comment counters are persisted. A missing first metrics response does not invalidate a confirmed upload. Data API counters are not revenue; estimated or actual monetization revenue is handled separately in BUILD-00009.

OAuth credentials are supplied through environment secrets; an interactive OAuth consent UI/token provisioning flow is not included. The initial adapter supports one authenticated YouTube channel per runtime. Mocked tests are committed; real OAuth, upload quota, media processing and live metrics have not been validated.

## BUILD-00009 — financial ledger

Financial records are source-referenced inputs, not inferred earnings. APIs require `X-Review-Token`:
- POST `/api/finance/ledger` — record one revenue/cost item.
- GET `/api/finance/report?brand=...&from_date=...&to_date=...&currency=USD` — separate revenue/cost totals, net and ROI.

Use entry types `youtube_ads`, `affiliate`, `sponsor`, `production_cost`, `platform_fee`, `other_cost`. Every entry needs a source type and stable source reference. The same source/type reference cannot be double-counted. Reports are one currency at a time; no FX conversion or automatic revenue import is implemented.

## BUILD-00010 — performance insights

GET `/api/performance/insights?brand=...` requires `X-Review-Token`. It reports brand-level video snapshot differences and recorded ledger totals. It does not estimate earnings from views or infer trends from a single snapshot. Recommendations are rule-based and include their evidence basis. YouTube retention/watch-time, controlled experiments and autonomous strategy updates are not implemented.

## BUILD-00011 — persistent scheduler

Run `python scheduler.py` as a separate supervised process from the API and production worker. It dispatches due interval schedules to the durable queue with deterministic idempotency keys. API endpoints POST/GET `/api/schedules` and PUT `/api/schedules/{id}/activation?active=true|false` require `X-Review-Token`. Schedules are hourly or less frequent and validate active brand/market settings. Operate one scheduler instance only; distributed scheduler locking and calendar/DST rules are not implemented.

## Integrated Docker Compose deployment

At repository root, copy `.env.example` to `.env`, set a long random `NEXUS_REVIEW_TOKEN`, configure provider URLs/tokens and YouTube OAuth secrets. Then run:

```bash
docker compose build
docker compose up -d
docker compose ps
```

API health: `http://localhost:8502/api/health`. Compose starts the API, one production worker and one scheduler, all using a persistent shared SQLite volume. Run only one scheduler. This is a single-host baseline; do not treat it as HA production infrastructure.

Run the validation script with Python dependencies installed:

```bash
sh scripts/validate.sh
```

It performs bytecode compilation and discovers all unittest cases. A successful mocked test suite still does not validate real AI providers, OAuth, upload, monetization, or live revenue.

### YouTube upload media safety

YouTube upload accepts only staged files resolved inside `NEXUS_MEDIA_DIR` (default `data/media`). Supported extensions: MP4, M4V, MOV and WebM. The upload validates file existence, non-zero size and `NEXUS_MAX_MEDIA_BYTES` (default 256 MiB), and derives the MIME type from the extension. Paths outside the staging root and symlink escapes are rejected. The renderer currently returns a remote URL; an authenticated, allowlisted downloader must stage that artifact before upload. Do not pass arbitrary host paths to the API.

### API authentication

Operational endpoints require `X-Review-Token: <NEXUS_REVIEW_TOKEN>`. This includes production, trends, competitor intelligence, opportunities, schedules, review, YouTube, finance, performance, queue and worker operations, plus brand activation. Public endpoints are limited to health and read-only brand catalog/detail. Configure a long random secret and protect it; the shared token is not multi-user authentication.

### Secure renderer artifact staging

Set `RENDER_ARTIFACT_HOSTS` to exact comma-separated hostnames used by the configured render provider. After rendering completes, call:

```http
POST /api/production/jobs/{job_id}/stage-media
X-Review-Token: <NEXUS_REVIEW_TOKEN>
```

The service retrieves the artifact URL from the production record (the caller cannot supply an arbitrary URL), requires HTTPS and an allowlisted public hostname, rejects redirects, validates MP4 MIME/signature, enforces `NEXUS_MAX_MEDIA_BYTES`, and atomically stores it under `NEXUS_MEDIA_DIR`. Use the returned relative `media_path` in the subsequent YouTube upload request. CDN compatibility must be verified with the actual renderer provider.

### Approved uploads

The protected `GET /api/review/approved` endpoint lists approved productions. The dashboard's approved queue lets the operator explicitly stage the saved render artifact and initiate a YouTube upload. Upload remains private; approval alone does not publish publicly.

## Web operations portal

The integrated single-page control center is served from the backend:

```text
http://localhost:8502/
```

The UI includes production job intake, trends, competitors, profitability scoring, human review, approved/private upload, schedules, financial ledger and performance insights. Enter the configured `NEXUS_REVIEW_TOKEN` using the settings button. The token is kept in browser memory only and is cleared on reload. Public publishing is not offered by the UI; YouTube uploads remain private.

### Integration preflight

Use protected `GET /api/preflight` (header `X-Review-Token`) or the dashboard readiness panel to identify missing environment settings. It checks configuration presence only; it does not make provider, OAuth or YouTube API calls.

Dashboard supports USD, KRW, JPY and GBP for ledger entries and profitability scenarios. Financial reports filter by one currency at a time; currency conversion is not inferred or applied.


### Staged media retention and cleanup

- A staged MP4 is retained when upload fails, is active, or requires reconciliation. Do not delete it while the remote upload outcome is uncertain.
- After the upload ledger reports `status=uploaded` with a confirmed YouTube video ID, an operator may call `POST /api/production/jobs/{job_id}/cleanup-media` with `X-Review-Token`. The endpoint deletes only the deterministic staged file belonging to that job; repeated calls are safe.
- Abandoned atomic-write `.part` files can be pruned with `MediaStager.prune_temporary_files()` after a minimum one-hour age threshold. It never scans or deletes completed media files. No automatic retention job is enabled by default.
- Keep the renderer's remote artifact until upload is confirmed and your provider's retention policy permits deletion. Remote artifact deletion is not implemented.


## Retry, cancellation and orphan-artifact consistency — 2026-11-15

- A new production attempt now deletes the previous attempt's script/audio/video artifact rows in the same SQLite transaction as the fenced transition into the script stage. This prevents an old rendered MP4 from remaining visible as the current attempt's output after a retry starts.
- Worker startup now reconciles durable queue states `cancelled` and `failed_terminal` into the matching production record. The reconciliation is transactional and does not overwrite approved/uploaded records.
- Added regression tests for retry invalidation and cancellation-state synchronization.
- This does **not** delete remote renderer artifacts; provider-side cleanup is not implemented because ownership and retention guarantees depend on the configured renderer.
- Tests are committed but have not been executed in a Python runtime. GitHub Actions currently fails before allocating a runner; no assertion result is available.


## YouTube upload/reconciliation race protection — 2026-11-15

- YouTube upload finalization now uses `BEGIN IMMEDIATE` and updates only a row still in `uploading`. A late remote completion cannot overwrite an operator's `not_uploaded` reconciliation or another terminal state.
- Reconciliation itself now acquires the SQLite write transaction before reading and deciding the upload state, serializing it against finalization and other reconciliation attempts.
- Added regression coverage for a late upload response after operator reconciliation and for attempts to finalize a missing upload record.
- If the remote response arrives after reconciliation has already declared no upload, the local record remains failed and the late result is surfaced as an error for manual investigation; operators must check YouTube Studio before any new upload attempt.
- Tests are committed but remain unexecuted until a GitHub Actions runner or local Python environment is available.


### Review decision concurrency check

Review decisions are committed in a BEGIN IMMEDIATE transaction. The production status transition is checked using the UPDATE statement's affected-row count; if the row is no longer review_pending, the decision transaction is rolled back rather than accepted as successful.


## 2026-11-15 — YouTube late-success preservation and reconciliation audit

- Added append-only `youtube_upload_events` records for operator reconciliation, late remote success, and operator resolution. Each record includes job ID, outcome, returned video ID where available, operator ID, note, previous/resulting state and UTC timestamp.
- A late YouTube response arriving after an operator marked `not_uploaded` is now persisted as `late_success_review_required`; the video ID is retained and new upload attempts are blocked. The late response cannot be overwritten by the stale request's error handler.
- Added authenticated `POST /api/youtube/uploads/{job_id}/resolve-late-result`. An operator must acknowledge the preserved video ID and provide an audit note before the upload is finalized as private.
- The dashboard distinguishes this state from ordinary ambiguous uploads and provides an explicit resolution action. Reconciliation requests include the dashboard reviewer ID; this is caller-supplied identity, not cryptographic user authentication. The shared review token remains a transitional access control.
- Added regression assertions for preserved late IDs, retry blocking, operator attribution and event timestamps. These tests are committed but have not yet been executed in a Python runtime; do not treat source review as a passing test run.


### Upload-attempt fencing and late-response quarantine — 2026-11-15

- Each YouTube upload attempt now receives a fresh persisted generation token. Finalization, heartbeat, ordinary failure and ambiguous-outcome transitions are fenced against that token, so a stale request cannot update a newer retry's state.
- If an older attempt returns a video ID after a newer attempt has started, the ID is appended to the immutable upload-event ledger and the job enters `late_success_review_required`; further retries are blocked. If an older attempt terminates ambiguously after a retry starts, it creates a `superseded_attempt_uncertain` event and quarantines the current job in `reconciliation_required`.
- SQLite triggers reject UPDATE and DELETE operations on `youtube_upload_events`. The operator resolution endpoint now requires selection of a video ID present in the late-success event history. The dashboard displays preserved late IDs before resolution.
- This protects local state and prevents further automatic retries; it cannot delete a duplicate video already created remotely. If multiple remote video IDs are present, the operator must inspect YouTube Studio, choose the canonical video, and manually remove any unwanted duplicate according to channel policy.
- Regression tests cover stale completion after retry and ambiguous old-attempt failure. Runtime execution remains unverified until a Python test runner is available.


### CI verification status — 2026-11-15

The latest workflow run observed during this update was [run 43662557760](https://github.com/justinhblee-prog/shorts/actions/runs/43662557760), for HEAD `fa5fe6bc45d88c18821836727df1f1ac8f0e0f4c`. GitHub reports the job completed with failure but `runner_id=0`, empty runner name and `steps=[]`; therefore no Python test command ran. Several immediately preceding runs show the same pre-runner failure. This is an infrastructure/runner-allocation failure, not a failing test assertion and not a passing test result. All YouTube attempt-fencing and audit tests remain unexecuted pending a working runner or local Python environment.


### SQLite upload transition runtime check — 2026-11-15

- Fixed a runtime defect in `YouTubeUploadStore`: SQLite `rowcount` belongs to the cursor returned by `execute()`, not the connection object. Upload completion, heartbeat, reconciliation and late-success resolution now inspect the returned cursor's `rowcount`.
- Added a regression test ensuring a stale worker error cannot downgrade a confirmed `uploaded` record. Normal upload completion is also written to the immutable event ledger as `upload_confirmed`.
- Executed a focused Python/SQLite integration harness in the available local Python runtime against the upload-store logic. **Passed 3 scenarios:** late-success quarantine + retry blocking + operator resolution + immutable events; successful completion + audit event + no heartbeat mutation after completion; ambiguous reconciliation + operator attribution. This is targeted store-level execution, not the complete repository test suite or a live YouTube upload.
- GitHub Actions remains unavailable: recent runs terminate before runner allocation (`runner_id=0`, no steps). The full suite and browser/live-provider tests remain unverified.


### Cross-module SQLite cursor correction — 2026-11-15

- A broader source scan found the same SQLite API misuse in production recovery and review decisions. Replaced connection-level `c.rowcount` / cumulative `total_changes` checks with the `rowcount` of each individual cursor returned by `execute()` in `production_pipeline.py`, `review_workflow.py`, and `youtube_publishing.py`.
- Affected paths: production run stage existence checks; missing-run insertion accounting; terminal-job reconciliation; review-pending repair; human review state transition; upload finish; upload heartbeat; upload reconciliation; late-success resolution.
- This corrects real runtime exceptions and avoids false-positive row-change detection caused by cumulative connection change counts. The earlier targeted Python/SQLite upload-store scenarios passed after applying the cursor-based fix in the harness. The complete repository suite still has not run.


### Canonical-video resolution after late duplicate response — 2026-11-15

- Late-success resolution now accepts either the currently recorded confirmed video ID or a video ID in the immutable late-success event ledger. This lets an operator retain the already confirmed canonical upload when a stale attempt later reports a second video.
- The dashboard explicitly distinguishes the current recorded ID from late-response IDs and tells the operator either can be selected. Arbitrary, unrecorded IDs remain rejected.
- Added a regression test for the sequence: first attempt times out → operator confirms no upload → retry succeeds → stale first attempt returns a different video ID → job is quarantined → operator retains the canonical current ID. The targeted Python/SQLite harness passed this scenario against the store logic.


### Attempt-correlated immutable audit — 2026-11-15

- Added `attempt_id` to `youtube_upload_events`, with an additive migration for existing databases. Each attempt-start, confirmed upload, preflight failure, ambiguous outcome, superseded-attempt event, operator reconciliation and late-result resolution is now correlated to the specific generation token.
- The event history now captures normal upload start/completion and preflight/uncertain failure transitions as well as manual operator actions. UPDATE/DELETE protection remains enabled.
- Added regression coverage for legacy-schema migration, attempt correlation, and preflight/ambiguous failure event types. Executed SQLite checks for all nine event INSERT statement shapes and immutable-trigger behavior; all passed. This supplements the earlier focused state-transition harness, but does not replace the full pytest suite.


### Post-confirmation worker exception guard — 2026-11-15

- `mark_reconciliation_required()` now treats `uploaded` as terminal regardless of whether the incoming worker token matches the current attempt. It appends an informational immutable event (`post_confirmation_worker_error` or `superseded_attempt_uncertain`) and never downgrades the confirmed upload.
- Added regression assertions for both a stale worker token and a same-attempt exception occurring after confirmation. Both must preserve `status='uploaded'` and the confirmed video ID.


### Resolution audit generation attribution — 2026-11-15

- The late-result resolver now records the attempt generation associated with the selected video ID, rather than always attributing resolution to the currently active/latest attempt. Selecting a late video ID records that late response's attempt token; retaining the current video ID records the current attempt token.
- Regression tests assert both attribution paths.


### Late-upload API and dashboard regression coverage — 2026-11-15

- Added test coverage that the late-result resolution endpoint is registered and requires the review token, that the request model requires a video ID, and that the dashboard includes the current/late ID selection controls and API call.
- These are committed regression tests; they have not run in GitHub Actions because the hosted runner fails before job allocation.
