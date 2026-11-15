# Handover — NEXUS STUDIO PRO v0.1

## Repository
https://github.com/justinhblee-prog/shorts (private), default branch main.

## Current files
- `backend/queue_store.py`: SQLite queue, worker leases, idempotency, retry, events, cancellation and recovery.
- `backend/trends.py`: Google News RSS (KR/US/JP/GB), Hacker News Firebase API, source-preserving trend storage.
- `backend/youtube_intel.py`: YouTube Data API v3 channel/video intelligence and historical snapshots.
- `backend/profitability.py`: scenario-based revenue/cost/ROI calculator and opportunity ranking.
- `backend/app.py`: FastAPI API surface.
- `backend/requirements.txt`: runtime dependencies.
- `backend/tests/test_queue.py`: queue unit tests.
- `backend/README.md`: backend run instructions.
- `.github/workflows/backend-tests.yml`: CI workflow.
- `docs/BUILD_STATUS.md`: roadmap and validation ledger.

## Run locally
Python 3.11+:
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
uvicorn app:app --host 0.0.0.0 --port 8502
```

## API
- POST /api/trends/collect
- GET /api/trends
- GET /api/competitors
- POST /api/opportunities/score
- GET /api/opportunities/search?q=...
- GET /api/competitors/{channel_id}
- GET /api/competitors
- GET /api/health
- GET /api/queue/stats
- POST /api/jobs
- POST /api/jobs/claim
- POST /api/jobs/{id}/heartbeat
- POST /api/jobs/{id}/complete
- POST /api/jobs/{id}/fail
- POST /api/jobs/{id}/cancel
- POST /api/queue/recover
- GET /api/workers
- GET /api/jobs/{id}
- GET /api/jobs/{id}/events

## Important constraints
- A worker must present its current lease token for heartbeat/finish/fail.
- A stale or expired worker is rejected.
- Retryable jobs are claimable again until max_attempts is exhausted.
- Completion leads to review_pending, not public publishing.
- SQLite is the current local foundation; PostgreSQL migration is not implemented.
- Do not report tests as passing: CI has not reached a runner/job step yet, and no local runtime execution has been performed in this environment.

## BUILD-00002 status

Trend provider code and tests are committed, but not yet runtime-validated. Google News RSS is not a search-volume/YouTube-view source; such metrics remain null. Hacker News score/comment counts are only the source-provided values and must not be treated as video view metrics.

## BUILD-00004

Scenario-based opportunity scoring accepts explicit low/high view forecasts, RPM, costs, monetization eligibility, ancillary revenue assumptions, evidence quality, strategic fit and production feasibility. Forecast source is mandatory. Output is labeled estimate and stored with an explainable score breakdown. API: POST `/api/opportunities/score`, GET `/api/opportunities`. Unit tests are committed but not executed due to the runner initialization issue.

## BUILD-00003

YouTube channel search, channel snapshots and recent public video statistics are implemented in `backend/youtube_intel.py`. Set `YOUTUBE_DATA_API_KEY` in the runtime environment. The provider has fake-transport unit tests only; live API and quota behavior remain unverified. Search.list consumes substantial quota, so prefer known channel IDs.

## Immediate next task

Continue with BUILD-00007: explicit human review and approval workflow, including approve/reject/revision actions and immutable audit events. Preserve the hard rule that rendered media cannot be published publicly without an explicit human approval decision.

GitHub Actions remains blocked before runner allocation (latest inspected job had runner_id=0 and no steps). The source and mock tests for BUILD-00005 and BUILD-00006 are committed but have not been executed in a Python runtime. Do not report runtime or live-provider success until verified.

Resolve GitHub Actions runner/job initialization. Latest run is https://github.com/justinhblee-prog/shorts/actions/runs/43653621860; it reports a failed job with no step summaries and no logs, so the Python tests did not execute. Then run the documented Python 3.11+ unittest command, fix failures, and only then close BUILD-00001.


## BUILD-00005 — production pipeline

New files:
- `backend/worker.py`: long-running worker, job-type-specific claims, lease heartbeats, and review-gate completion.
- `backend/production_pipeline.py`: durable production run/artifact store, JSON provider adapter, and script → voice → render orchestration.
- `backend/tests/test_production_pipeline.py`: mocked contract tests.

Updated `backend/app.py` endpoints:
- `POST /api/production/jobs`
- `GET /api/production/jobs/{job_id}`
- `POST /api/production/jobs/{job_id}/execute`

The execution endpoint requires a job already claimed through the durable queue and validates the current worker ID and lease token. Alternatively, run `python worker.py` from `backend/` to run a long-lived worker that claims only production jobs and renews the lease during provider calls. Configure `SCRIPT_PROVIDER_URL`, `VOICE_PROVIDER_URL`, and `RENDER_PROVIDER_URL`; optional tokens use the matching `*_TOKEN` variables. Provider contracts and exact request/response requirements are documented in `backend/README.md`.

A successful pipeline stores script text, audio URL and rendered video URL, then moves the queue job to `review_pending`. No publish call exists. This source milestone is committed but not runtime-tested. Mock tests are not evidence of real provider compatibility or real generated media.


## BUILD-00006 — brand operations

New file: `backend/brand_operations.py` — seeds and persists the ten brand profiles and exposes active-state controls through the API. Profiles include editorial risk and review rules, region/language support and positioning. Production job submission validates the selected active brand and supported market.

New tests: `backend/tests/test_brand_operations.py`. Tests are committed but not executed in a Python runtime.


## BUILD-00007 — review workflow

New file: `backend/review_workflow.py`; tests: `backend/tests/test_review_workflow.py`.

Set a strong `NEXUS_REVIEW_TOKEN` secret in the backend runtime. Send it in the `X-Review-Token` header for every review endpoint. The API deliberately denies access when the secret is absent. Provide a non-empty `reviewer_id`; rejection and revision requests also require a reason. Each decision stores an artifact snapshot and append-only audit entry. A decision cannot be overwritten. Approval changes the production record to `approved` only; it does not publish or upload.

Endpoints:
- GET `/api/review/pending`
- POST `/api/review/{job_id}/approve`
- POST `/api/review/{job_id}/reject`
- POST `/api/review/{job_id}/request-revision`
- GET `/api/review/{job_id}/history`

All review endpoints require `X-Review-Token`. These endpoints are not a substitute for user-specific identity/role management; the current baseline uses one shared operator secret and an asserted reviewer ID. Runtime test execution and deployment hardening remain outstanding.

## BUILD-00008 — YouTube private upload

New module: `backend/youtube_publishing.py`; tests: `backend/tests/test_youtube_publishing.py`.

Set runtime secrets `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`. The refresh token must have `https://www.googleapis.com/auth/youtube.upload` and `https://www.googleapis.com/auth/youtube.readonly` scopes. Never commit credentials.

Only a production job with a recorded `approved` decision can be uploaded. The adapter hard-codes `privacyStatus=private`; there is no public publishing endpoint. Upload endpoint requires `X-Review-Token`:
- POST `/api/youtube/upload/{job_id}` with `media_path`, `title`, optional `description`, `tags`, `category_id`.
- GET `/api/youtube/uploads/{job_id}`.
- POST `/api/youtube/videos/{video_id}/refresh-metrics`.

The media file must exist on the API server. Existing render adapters return a remote URL; the secure media download/staging adapter remains to be built. The current OAuth configuration supports one channel per runtime. Upload ledger and Data API view/like/comment snapshots are persisted; these are not revenue figures. Tests are mocked and not yet executed. No live OAuth/upload has been performed.

## BUILD-00009 — financial ledger

Module: `backend/ledger.py`; tests: `backend/tests/test_ledger.py`.

Use POST `/api/finance/ledger` with a source-backed record. Revenue types are `youtube_ads`, `affiliate`, `sponsor`; cost types include `production_cost`, `platform_fee`, `other_cost`. Source types are allowlisted. A source reference is mandatory and idempotent within source/type. GET `/api/finance/report` groups totals and calculates net/ROI for one currency at a time. Both endpoints require `X-Review-Token`. Data is recorded input; no RPM-to-revenue inference. Automatic Analytics/affiliate/sponsor reconciliation and currency conversion are not implemented.

## BUILD-00010 — performance insights

Module: `backend/performance_insights.py`; tests: `backend/tests/test_performance_insights.py`.

GET `/api/performance/insights` optionally filters by brand and requires `X-Review-Token`. It compares first/last stored public-counter snapshots and combines manually/source-integrated financial ledger entries. It labels view changes as snapshot differences, not velocity. Less than two snapshots yields insufficient evidence rather than a guessed result. Recommendations are fixed transparent heuristics, not causal analysis or automatic actions. Watch time, retention, experiments and automated strategy changes remain future work.

## BUILD-00011 — scheduler

Files: `backend/scheduler_store.py`, `backend/scheduler.py`, tests `backend/tests/test_scheduler.py`.

Run one scheduler process using `python scheduler.py` from backend. It polls persistent schedules and dispatches due production jobs to the durable queue. The deterministic idempotency key prevents duplicate queue jobs if dispatch is retried. Missed intervals are skipped forward; minimum interval is one hour. API endpoints POST/GET `/api/schedules` and PUT `/api/schedules/{id}/activation?active=true|false` require `X-Review-Token`. Current scheduler is single-instance; do not run multiple schedulers against production until a distributed leader/lease is implemented.

## BUILD-00012 — integrated package

Root files: `compose.yaml`, `.env.example`; image: `backend/Dockerfile`; validation script: `scripts/validate.sh`.

1. Copy `.env.example` to `.env` and replace the review token and provider/OAuth credentials.
2. Run `docker compose build` and `docker compose up -d`.
3. Check `http://localhost:8502/api/health`.
4. Run `sh scripts/validate.sh` in an environment with the backend dependencies installed.

Compose starts API, one worker and one scheduler sharing a persistent SQLite volume. Keep one scheduler instance. This is a single-host validation baseline, not production-hardened HA. Configure HTTPS reverse proxy, backups/restore, log monitoring, OAuth refresh-token issuance and real provider endpoints before external launch. Never commit `.env`.

## Final integrated baseline and external launch blockers

BUILD-00001 through BUILD-00012 have source baselines committed to `main`. This does not establish a tested or revenue-producing production system.

Before live launch:
1. Resolve GitHub Actions runner allocation or execute `sh scripts/validate.sh` in a working Python 3.11+ environment.
2. Configure real script/TTS/render provider endpoints and validate actual generated artifacts.
3. Add secure download/staging of remote rendered media; YouTube upload currently requires a server-local file path.
4. Issue YouTube OAuth refresh credentials with upload/read scopes and validate a private test upload.
5. Connect actual YouTube Analytics, affiliate and sponsor financial sources to the ledger.
6. Replace the shared review token with authenticated users/roles; configure TLS, secret rotation, backups, monitoring and incident recovery.
7. Migrate SQLite and add distributed worker/scheduler coordination before scaling beyond a single host.
8. Verify actual revenue, costs and net ROI on a controlled content cohort before declaring business success.

Latest checked CI run 74: runner_id=0, no runner name and no steps. Tests have not run. A clone attempt from this execution environment could not resolve github.com. The source is committed; runtime and live integration are unverified.

## YouTube upload media-path hardening

Upload paths are now constrained to `NEXUS_MEDIA_DIR` (default `data/media`), canonicalized to prevent traversal/symlink escape, restricted to MP4/M4V/MOV/WebM, and bounded by `NEXUS_MAX_MEDIA_BYTES` (default 256 MiB). This reduces arbitrary local-file upload exposure. It does not implement remote renderer artifact download; an authenticated allowlisted staging service remains a launch blocker.

## Operational API token coverage

All operational endpoints now require `X-Review-Token`: brand activation, production job creation/execution/inspection, trend and competitor operations, opportunity scoring, queue/worker/job operations, review, YouTube, finance, performance and schedules. Public exceptions are health and read-only brand catalog/detail. Regression test `backend/tests/test_api_security.py` checks route coverage and token validation. The shared token remains a transitional single-operator control; do not expose the service publicly without TLS and real user/role authentication.

## Renderer artifact staging

Configure `RENDER_ARTIFACT_HOSTS` with comma-separated exact CDN hostnames returned by the renderer. After a production job reaches `rendered` / `review_pending`, call POST `/api/production/jobs/{job_id}/stage-media` with `X-Review-Token`. The endpoint reads the saved artifact URL, downloads only HTTPS MP4 from allowlisted public hosts, rejects redirects/private DNS/IPs, enforces the configured size cap and writes atomically to `NEXUS_MEDIA_DIR`. The response returns a relative `media_path` suitable for the YouTube upload request. Live CDN compatibility and video playback remain unverified.

## CI state after API security and media staging changes

Latest observed run 84 (2026-11-15) failed before runner allocation: `runner_id=0`, empty runner name, `steps=[]`. This is not a test failure and not a test pass. API security and media-staging regression tests are committed but unexecuted. Latest run: https://github.com/justinhblee-prog/shorts/actions/runs/43656898926.

## Approved queue and private upload UI

The dashboard now includes an approved-production list backed by `GET /api/review/approved`. An operator can explicitly stage the saved artifact and initiate private YouTube upload from that list. Media staging accepts the `approved` state so a previously approved job can be staged and retried. Public publishing is not exposed.

## Single-page dashboard

FastAPI serves `frontend/index.html` at `/` and assets at `/assets`. The dashboard contains production intake, trend collection, competitor search, profitability scoring, review queue, approved/private upload queue, schedules, finance and performance. Token entry is in-memory only (not localStorage/sessionStorage); reload clears it. The approved queue is `GET /api/review/approved`; an operator can explicitly stage the stored MP4 artifact and upload privately. Dockerfile copies frontend assets into the image.

UI integration and responsive browser behavior have not yet been tested in a live browser. The backend CI runner has been intermittently failing before runner allocation; no claims of UI or full-suite validation.

## Dashboard packaging test

Added `backend/tests/test_frontend.py` to check that the three static assets exist, FastAPI exposes the dashboard and asset mount, and all four primary workspaces are present. This is a packaging/static test, not browser automation. Latest Actions run 103 had no allocated runner and no steps; a rerun was requested but not yet verified.

## Operator runbook

See `docs/OPERATOR_RUNBOOK.md` for configuration, Docker deployment, production lifecycle, artifact staging security, financial controls, recovery and the external launch validation checklist.

## Integration preflight

Protected `GET /api/preflight` reports which configuration groups are present, without returning secret values. Dashboard displays operator auth, AI provider, renderer artifact allowlist, YouTube OAuth/Data API and media directory readiness. The report is configuration-only and never claims live connectivity. Tests: `backend/tests/test_preflight.py`.

Latest checked CI run 103 (2026-11-15): https://github.com/justinhblee-prog/shorts/actions/runs/43657516480. Job has `runner_id=0`, no runner name and no steps. The newest security, media staging, dashboard, Docker layout and preflight changes have not executed under CI. Do not mark tests passed.

Dashboard currency selectors support USD/KRW/JPY/GBP for financial ledger entries and profitability scenarios. The reporting API remains currency-filtered; no implicit FX conversion is performed.

Latest observed run 106 (commit `efa84562519ea814f9f10d5e030c8c3b5f2f131e`) failed before runner allocation: `runner_id=0`, no runner name, no steps. Latest code changes remain untested by CI.

## BUILD-00010 — performance insights

`GET /api/performance/insights` now returns `brands`, `regions`, `videos`, `financial` (array grouped by brand/currency), and `limitations`. It excludes negative view-counter differences from growth totals, labels invalid/reset measurements, and applies the brand filter to financial records too. Dashboard renders these evidence groups. Recommendations are heuristics only, not forecasts.

## BUILD-00011 — scheduler outbox recovery

The scheduler atomically reserves due occurrences and writes them to `schedule_dispatch_outbox`. Queue enqueue uses `schedule:{schedule_id}:{scheduled_for}` idempotency. Pending outbox records are replayed on each poll; a crash between queue enqueue and outbox acknowledgement cannot duplicate the job. Failures remain pending with attempt count and bounded error text. Test file: `backend/tests/test_scheduler_store.py`.

Scheduler observability endpoint: authenticated `GET /api/schedules/outbox` returns pending/dispatched counts and recent occurrence attempts/errors. It is diagnostic only; the scheduler process retries pending records on its normal polling loop.

Latest CI run 114 (commit `b3f6ae65669af361f4c7fa6314e9d9c2c832fd30`) again failed before runner allocation: `runner_id=0`, empty runner name, `steps=[]`. The new analytics and scheduler outbox tests are not executed.

Latest run 115 (2026-11-15) again failed before runner allocation (`runner_id=0`, empty runner name, zero steps). The source and test commits are present, but test execution remains unverified.

## BUILD-00012 — integration lifecycle and crash recovery

New test: `backend/tests/test_end_to_end_lifecycle.py`. It drives a job through durable queue, fake script/voice/render providers, persisted artifacts, human approval, fake allowlisted CDN staging, fake YouTube private upload and ledger records. All provider/CDN/YouTube adapters are mocked; do not treat this as live validation.

Crash recovery: `ProductionStore.reconcile_review_pending(queue)` advances only production records still in `rendered` when the durable queue confirms the matching `short_video_production` job is already `review_pending`. It is called before worker claims and before the API returns pending reviews. This repairs the process-crash window between `queue.finish()` and the production-store status update without promoting a job whose queue state is not complete.

Latest CI run 122 for commit `2eff2834db260134f97ef72a66f54409e406bfbb` did not allocate a runner (`runner_id=0`, no runner name, zero steps). No assertion or test result is available. Source review only; runtime validation is still pending.

Run 123 for HEAD `6a42c46d451218dd24dfd10ab41de7ec7bee0000` confirms the same runner allocation failure (`runner_id=0`, empty runner name, zero steps). No test execution evidence is available.
## YouTube upload ambiguous-outcome recovery

The upload path now avoids a duplicate-video hazard when a resumable upload has started but the client loses the final response.

- Before the remote request begins, ordinary initialization failures remain `failed` and can be retried.
- After `videos().insert()` returns a resumable request, exceptions or a missing final video ID become `reconciliation_required`. The job cannot be retried automatically.
- A live `uploading` attempt refreshes its activity timestamp in a background heartbeat and after completed resumable chunks. Manual reconciliation is blocked until the attempt is stale for `NEXUS_UPLOAD_STALE_SECONDS` (default 900 seconds, minimum 60).
- Authenticated endpoint: `POST /api/youtube/uploads/{job_id}/reconcile`.
  - `outcome=uploaded`: operator must confirm and supply the video ID found in YouTube Studio.
  - `outcome=not_uploaded`: operator must confirm that no matching upload exists; this makes the job retryable.
  - Both outcomes require an operator note.
- Dashboard exposes an explicit “업로드 결과 대조” action only for stale or uncertain attempts. Active attempts show as in progress.
- Never select `not_uploaded` without checking the intended channel's private uploads in YouTube Studio. The reconciliation operation is an operator assertion, not an automated YouTube-side lookup.
- Tests were added but remain unexecuted until a GitHub Actions runner actually starts.

### Upload authorization re-check — 2026-11-15

- YouTube upload now requires the **latest** review decision to be `approved`; an earlier approval does not survive a later revision/rejection decision.
- The upload claim re-checks both `production_runs.status='approved'` and the latest `review_decisions.decision='approved'` under `BEGIN IMMEDIATE` in the same SQLite database transaction that claims the upload. This closes the check-then-claim gap against concurrent review-state changes.
- Regression tests cover a later revision decision and a production record that is no longer approved. Tests are committed but remain unexecuted pending a working GitHub Actions runner.

### Worker lease fencing for production writes — 2026-11-15

- `ProductionStore.stage()` and `ProductionStore.artifact()` accept worker identity plus lease token and validate the live `pipeline_jobs` row under `BEGIN IMMEDIATE` before changing production state or artifact records.
- `ProductionPipeline.execute()` carries the claim's worker ID and token through every stage and artifact write. Lease conflicts are propagated without marking the production run failed, preventing an expired worker from overwriting a replacement worker's state.
- The worker now passes its claim token into the pipeline. The end-to-end lifecycle test does the same.
- Added a regression test that expires and reclaims a job, proves the old token cannot start or write an artifact, and proves the new token can complete production.
- Existing direct pipeline unit tests remain supported without a lease context for isolated component tests; the production worker always supplies one.
- Tests are committed but not executed because GitHub Actions jobs continue to fail before runner allocation (no steps/logs available).
- Review handoff recovery now performs a single SQLite `BEGIN IMMEDIATE` transaction joining `production_runs` to `pipeline_jobs`; it promotes only jobs whose durable queue status is still `review_pending`. A cancellation between queue completion and review handoff therefore cannot be overwritten by a stale worker.


### Queue-to-production crash recovery — 2026-11-15

- Added idempotent recovery for the enqueue/production-row creation gap. If the process stops after a durable queue insert but before the corresponding `production_runs` insert, the worker reconstructs the production row from the validated queue payload before claiming work and again immediately after a claim to close the concurrent enqueue race.
- Production-row creation now uses `INSERT OR IGNORE` so a concurrent recovery and submitter cannot fail each other with a duplicate-key error.
- Recovery is restricted to `short_video_production` jobs in queued, retryable-failure or running states, uses the same SQLite database and `BEGIN IMMEDIATE`, and is idempotent. Invalid payloads are reported as skipped rather than turned into fabricated production records.
- Added regression tests for recovery after an enqueue crash and for the race where a worker claims the job before recovery.
- Tests are committed but not executed; GitHub Actions runner allocation remains an external validation blocker.

 
## Media artifact lifecycle hardening — 2026-11-15

- Added an operator-authenticated cleanup endpoint: `POST /api/production/jobs/{job_id}/cleanup-media`.
- A staged file is eligible for deletion only when the durable YouTube upload ledger reports `status=uploaded` and a non-empty confirmed video ID. Failed, active and reconciliation-required uploads retain their media for recovery.
- Cleanup targets only the deterministic per-job MP4 path, rejects symlink targets/path escapes, and is idempotent.
- Added conservative pruning for abandoned `.nexus-*.part` temporary downloads, with a minimum one-hour age threshold. Completed media files are never included in this sweep.
- No automatic deletion timer is enabled. Remote renderer artifact deletion is not implemented; retain remote source artifacts according to provider retention terms.
- Regression tests were added for upload-gated cleanup, repeat cleanup, temporary-file age and preserving completed media. **These tests have not been executed in a Python runtime**; CI runner initialization remains an external blocker.


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


## 2026-11-15 — Review/upload state-machine audit

- Fixed the YouTube upload race regression tests to use the actual YouTubeUploadStore fixture (self.uploads), eliminating a test-time AttributeError that static review had missed.
- Hardened ReviewStore.decide() to verify the guarded production status update via its statement-level rowcount, not SQLite connection-wide cumulative total_changes.
- No runtime test result is claimed; GitHub Actions runner allocation and local Python execution remain unavailable.


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
