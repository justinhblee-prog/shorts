# NEXUS STUDIO PRO — Development Status

**Baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Updated:** 2026-11-15

## Business objective

Automate a profitable short-form video operation: global topic discovery → evidence-backed opportunity scoring → script/voice/video production → human review → publishing → measured revenue and cost analysis → strategy improvement.

Business success is measured by verified net revenue, ROI, content throughput, and operating cost. Forecasts remain estimates. Public publishing requires explicit human approval.

## Brand portfolio

1. Brain Glitch — neuroscience and psychology
2. Silent Signals — relationships and nonverbal psychology
3. Unseen Truth — history and hidden context
4. Dark Files Global — space, deep sea, mysteries
5. 99% Missed — everyday knowledge and productivity
6. Money Glitch — economics and finance
7. Secret Vault 24 — corporate and economic secrets
8. Future Leak — AI and future technology
9. 30Sec Shift — health, sleep and longevity
10. Why Nobody Tells — social and business insights

## Build roadmap

| ID | Scope | State |
|---|---|---|
| BUILD-00001 | Durable queue and Worker Lease | Source implemented; execution validation blocked |
| BUILD-00002 | Global trend ingestion | Provider/API/tests implemented; live and runtime validation pending |
| BUILD-00003 | Competitor/channel intelligence | Provider/API/tests implemented; API-key and runtime validation pending |
| BUILD-00004 | Profitability scoring and prioritization | Scenario calculator/API/tests implemented; runtime validation pending |
| BUILD-00005 | AI script, voice and video pipeline | Provider orchestration, lease-aware worker and API implemented; mocked tests committed; runtime/live-provider validation pending |
| BUILD-00006 | Ten-brand operations | Persistent 10-brand registry, activation controls and production market validation implemented; runtime validation pending |
| BUILD-00007 | Review and approval workflow | Decision store, authenticated APIs, audit snapshots and tests committed; runtime validation pending |
| BUILD-00008 | YouTube publishing and tracking | OAuth refresh-token adapter, approval-gated private resumable upload, upload ledger and Data API counter snapshots committed; live validation pending |
| BUILD-00009 | Revenue, cost and ROI analytics | Source-referenced financial ledger and separate revenue/cost reports committed; provider reconciliation pending |
| BUILD-00010 | AI performance analysis and strategy updates | Source implementation expanded: brand/region/video evidence, measurement coverage, reset detection and currency-safe financial grouping; runtime validation pending |
| BUILD-00011 | Scheduling and recovery operations | Durable schedule outbox, atomic due-occurrence reservation and idempotent crash replay implemented; runtime validation pending |
| BUILD-00012 | Integrated validation and deployment | Docker Compose API/worker/scheduler packaging and validation script committed; deployment/test execution pending |

## BUILD-00001 — durable queue and Worker Lease

- SQLite durable queue with WAL, foreign keys, busy timeout and safe connection cleanup.
- Serialized claim transactions using BEGIN IMMEDIATE.
- Worker lease expiry and UUID fencing token.
- Heartbeat, completion, failure, retryable re-claim and terminal retry handling.
- Idempotency key on enqueue; event history and worker registry.
- Operator cancellation and expired-lease recovery APIs.
- Successful worker completion moves a job to review_pending; this milestone has no public publish transition.
- Tests cover idempotency, exclusive/concurrent claims, retry, stale worker fencing, cancellation and lease recovery.
- **Not complete:** runtime tests have not executed.

## BUILD-00002 — global trend ingestion

- Google News RSS provider for KR, US, JP and GB.
- Official Hacker News Firebase API provider using top-stories and item endpoints.
- Persistent `trend_signals` table with source URL deduplication and timestamps.
- Preserve provider metrics only; unavailable search-volume and video-view metrics remain null.
- API: POST `/api/trends/collect`; GET `/api/trends`.
- Provider and persistence unit tests committed; live and runtime validation pending.

## BUILD-00003 — competitor/channel intelligence

- YouTube Data API v3 channel search, channel statistics and recent public video statistics.
- Stores channel snapshots and video counters in SQLite.
- API: GET `/api/competitors/search?q=...`; GET `/api/competitors/{channel_id}`; GET `/api/competitors`.
- Requires runtime secret `YOUTUBE_DATA_API_KEY`; no key is committed.
- Search.list typically consumes 100 quota units; prefer known channel IDs.
- Counters are snapshots, not growth rates, view velocity, RPM or revenue.
- Fake-transport tests committed; live API validation pending.

## BUILD-00004 — profitability scoring

- Transparent low/high scenario model for forecast views, RPM, ad/affiliate/sponsor revenue and operating costs.
- Monetization eligibility gate sets ad revenue to zero when the channel is not eligible.
- A forecast source is mandatory; outputs are explicitly labeled estimates.
- Explainable priority score: margin 35%, ROI 25%, evidence quality 20%, strategic fit 10%, production feasibility 10%.
- SQLite persistence and API: POST `/api/opportunities/score`; GET `/api/opportunities`.
- Unit tests committed; runtime validation pending.

- Added `backend/worker.py`: long-running worker claims only short-video jobs, renews its lease during provider work, and finalizes successful jobs at the human review gate. Queue claim now supports job-type filtering. Artifact writes are retry-safe by stage.\n\n## Validation — current truth

- Code and tests are committed to the private repository main branch.
- Latest observed GitHub Actions run before this documentation update: https://github.com/justinhblee-prog/shorts/actions/runs/43654662581
- Latest inspected job metadata reported `runner_id=0`, empty runner name, and `steps=[]`; the job failed before checkout or dependency installation. This is an environment/runner initialization failure, not evidence of a Python test failure.
- The suite has not passed or failed on code behavior; it has not executed in a real Python runtime.
- No production worker, PostgreSQL, external AI generation, OAuth, rendering or YouTube publishing has been validated.
- Do not claim real earnings, real monetization or a complete automated business cycle.

## Remaining blockers before a real revenue-producing launch

1. **CI runner:** GitHub Actions run https://github.com/justinhblee-prog/shorts/actions/runs/43656517188 failed before any step (`runner_id=0`, empty runner name, `steps=[]`). No Python test has executed. Resolve runner allocation or run `./scripts/validate.sh` in an authorized Python 3.11+ environment.
2. **Provider credentials/contracts:** configure and validate real script, TTS and renderer endpoints; confirm provider-specific request/response contracts, cost, latency and licensing.
3. **Media handoff:** current renderer output is a remote artifact URL, while YouTube upload expects a server-local media file. Implement authenticated download, file-size/type validation, malware scanning, retention and local staging before live upload.
4. **YouTube OAuth:** issue and configure a refresh token with `youtube.upload` and `youtube.readonly`; validate channel identity, quota, private upload and processing on a test channel.
5. **Financial integrations:** connect YouTube Analytics, affiliate networks and sponsor billing to the source-backed ledger. Reconcile actual currency, refunds, taxes and platform adjustments.
6. **Security/operations:** replace shared review token with real user identity and roles; add HTTPS, secret rotation, audit export, backups/restore, monitoring, rate limits and incident recovery.
7. **Scale:** migrate SQLite to PostgreSQL and add distributed worker/scheduler coordination before multi-instance deployment.
8. **Commercial validation:** test one controlled content cohort across the ten brands; compare verified net revenue and costs before increasing production volume. No actual revenue or monetization is established yet.

All BUILD-00001 through BUILD-00012 source milestones have a committed baseline. This is **not** equivalent to a tested production system or a completed revenue-generating business. External credentials, real provider execution, YouTube channel authorization and actual financial data remain necessary.

## Versioning

- v0.1: initial repository and queue foundation.
- v0.11: minor improvements.
- v0.2: major integrated milestone.


## BUILD-00005 — AI script, voice and video production pipeline

- Added `backend/production_pipeline.py` with provider-neutral JSON HTTP adapters, persistent production run/artifact records, strict brief validation, and ordered script → voice → render orchestration.
- Added production job submission, inspection and lease-token-protected execution endpoints in `backend/app.py`.
- Requires runtime configuration for script, voice and render provider URLs; optional bearer tokens are supported. Vendor-specific endpoints must conform to the documented JSON contracts or be wrapped by a provider adapter.
- Missing provider configuration, missing script text, missing audio URL or missing video URL fails closed. No fake generation outputs are returned.
- A successful render ends at `review_pending`; no public publishing action is included.
- Mock-provider contract tests are committed in `backend/tests/test_production_pipeline.py`.
- **Not validated:** test execution, real provider API compatibility, real audio/video generation, media playback, render quality, or end-to-end production. GitHub Actions runner initialization remains unresolved.


## BUILD-00006 — ten-brand operations

- Added `backend/brand_operations.py` with persistent profiles for all ten planned brands: vertical, positioning, audience, tone, supported regions/languages, risk level and editorial review rules.
- Added list/detail/activation APIs: GET `/api/brands`, GET `/api/brands/{slug}`, PUT `/api/brands/{slug}/activation`.
- Production job creation now accepts only an active registered brand and validates the requested region/language against that brand profile.
- Default profiles are inserted idempotently; activation state is preserved across restarts.
- Added local SQLite unit tests in `backend/tests/test_brand_operations.py`; execution remains blocked by GitHub runner initialization.


## BUILD-00007 — human review and approval

- Added `backend/review_workflow.py` with a transactional review decision store.
- Pending queue exposes only production runs in `review_pending`.
- Approve, reject and revision-request decisions require a configured `NEXUS_REVIEW_TOKEN` sent as `X-Review-Token`; missing token configuration fails closed.
- Every decision records reviewer ID, timestamp, comment, previous status and a snapshot of the artifacts reviewed. Decision rows are append-only; a second decision cannot overwrite a prior decision.
- Reject and revision-request actions require a reason. Approval is a review state only; it does not publish or upload anything.
- APIs: GET `/api/review/pending`; POST `/api/review/{job_id}/approve`; POST `/api/review/{job_id}/reject`; POST `/api/review/{job_id}/request-revision`; GET `/api/review/{job_id}/history`.
- Added SQLite tests for pending items, decision audit, artifact snapshots, mandatory reasons, immutable decision state and fail-closed token validation.
- **Not validated:** test execution, deployment security, reviewer identity integration or connection to a public publishing workflow.

## BUILD-00008 — YouTube private publishing and counter tracking

- Added `backend/youtube_publishing.py`: refresh-token OAuth client, resumable media upload, persistent upload state and source-backed video counter snapshots.
- Upload requires a prior recorded human approval decision for the exact production job.
- Privacy is hard-coded to `private`; callers cannot request public or unlisted status.
- APIs: POST `/api/youtube/upload/{job_id}`; GET `/api/youtube/uploads/{job_id}`; POST `/api/youtube/videos/{video_id}/refresh-metrics`. All require `NEXUS_REVIEW_TOKEN`.
- Runtime secrets: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`; OAuth scopes: `youtube.upload` and `youtube.readonly`.
- The upload endpoint accepts a server-local media path. Remote artifact URL download/staging and multi-channel OAuth are not yet implemented.
- Added mocked tests for approval gating, private-only metadata, idempotent successful upload and source metrics persistence.
- **Not validated:** Python test execution, real OAuth, real media upload, YouTube processing, live counter retrieval or production quota.

## BUILD-00009 — financial ledger

- Added `backend/ledger.py` with an auditable SQLite ledger for YouTube ads, affiliate, sponsor revenue, production costs and platform fees.
- Requires source type, source reference, occurrence timestamp, currency, brand and region; source reference + source type + entry type is idempotent.
- Revenue and costs are reported separately; net and ROI are calculated only from recorded ledger inputs. No view-based revenue is fabricated.
- APIs: POST `/api/finance/ledger`; GET `/api/finance/report`; both require `NEXUS_REVIEW_TOKEN`.
- Added tests for totals, idempotency and mandatory source reference.
- **Not validated:** runtime tests, automated YouTube Analytics ingestion, affiliate-network integrations, sponsor invoice imports, FX conversion or tax/accounting reconciliation. Reports are single-currency and must not sum different currencies.

## BUILD-00010 — performance analysis

- Added `backend/performance_insights.py` to correlate uploaded-video snapshots, production brand/topic metadata and recorded financial ledger entries.
- Snapshot differences are explicitly labeled as differences, not view velocity. Fewer than two snapshots produce an insufficient-evidence recommendation.
- Recommendations are transparent operational heuristics; no causal claims, fabricated trends or AI-generated performance assertions.
- API: GET `/api/performance/insights?brand=...`, protected by `NEXUS_REVIEW_TOKEN`.
- Added tests for insufficient evidence, snapshot differences and ledger integration.
- **Not validated:** runtime tests, long-term cohorts, controlled experiments, YouTube Analytics watch-time/retention data, or automated strategy execution.

## BUILD-00011 — scheduling and recovery

- Added `backend/scheduler_store.py` for persistent interval schedules and idempotent due-job dispatch.
- Schedules are limited to hourly or less frequent intervals; missed intervals are skipped forward rather than creating a burst backlog.
- Dispatch uses a deterministic queue idempotency key derived from schedule ID and scheduled timestamp.
- Added `backend/scheduler.py` long-running scheduler process; it is separate from API and production worker.
- APIs: POST/GET `/api/schedules`; PUT `/api/schedules/{id}/activation?active=true|false`; all protected by review token. Creation validates active brand and region/language.
- Added tests for dispatch, missed interval handling and minimum interval.
- **Not validated:** runtime tests, process supervision, multi-instance scheduler leadership, timezone/DST calendar schedules or production alerting. Run one scheduler instance until distributed leader election is added.

## BUILD-00012 — integrated packaging and validation

- Added `backend/Dockerfile` for the FastAPI API, worker and scheduler image.
- Added root `compose.yaml` with API, production worker and one scheduler sharing a persistent SQLite volume.
- Added `.env.example`; secrets are placeholders only. Copy to `.env`, replace values, and never commit `.env`.
- Added `scripts/validate.sh` to run compileall and the complete unittest suite.
- Docker Compose deployment is a local/single-host baseline. SQLite shared-volume operation is not a horizontally scalable production database architecture.
- **Not validated:** image build, compose startup, tests, provider credentials, OAuth, YouTube upload, media playback, monitoring, backups, restore, TLS/reverse proxy or production traffic.

## Latest CI observation

The latest checked run (run 94) failed before runner allocation: `runner_id=0`, `runner_name` empty, and `steps=[]`. It did not execute checkout, dependency installation, compilation or tests. A local clone attempt from this execution environment also could not resolve github.com, so no alternate local test run was possible. Do not interpret this as code passing or failing.

## API security hardening (follow-up)

- Added fail-closed `X-Review-Token` checks to all operational endpoints: brand activation, production job create/execute/read, trend collection/read, competitor search/read, opportunity scoring/read and generic queue/worker/job operations.
- Health and read-only brand catalog/detail remain public. Review, YouTube, finance, performance and schedule endpoints were already token-protected.
- Added route-audit tests that fail if a future operational endpoint omits the token parameter, plus token acceptance/rejection checks.
- Shared token remains a single-operator transitional control; it is not user identity/role authorization.
- Tests have not been executed because GitHub Actions currently fails before runner allocation.

## Renderer artifact staging

- Added `backend/media_staging.py` to fetch the renderer's stored video artifact into the protected YouTube media staging directory.
- Requires HTTPS and an exact hostname allowlist in `RENDER_ARTIFACT_HOSTS`; rejects credentials, non-443 ports, redirects and non-public DNS answers.
- Uses a pinned resolved public IP with hostname TLS verification, bounded streaming, MP4 MIME/signature checks, temporary files and atomic placement.
- Added protected API: POST `/api/production/jobs/{job_id}/stage-media`; it uses the stored render artifact, not a caller-supplied URL.
- **Not validated:** actual renderer CDN hosts, live TLS/download, media playback, full test suite and YouTube upload. Configure exact artifact hostnames before use.

Latest observed Actions run: [43657516480](https://github.com/justinhblee-prog/shorts/actions/runs/43657516480). Job metadata: `runner_id=0`, empty runner name, `steps=[]`; no test command executed. No tests have been executed by CI.

## Web operations portal and approved upload workflow

- Single-page portal served at `/`; assets at `/assets`.
- Studio, intelligence, review, approved/private upload, schedule, finance and performance sections are integrated with protected APIs.
- Approved queue endpoint: `GET /api/review/approved`.
- Renderer artifacts can be staged with protected `POST /api/production/jobs/{job_id}/stage-media`; exact host allowlisting and MP4 validation apply.
- YouTube upload UI calls the private-upload API only.
- Operator runbook: `docs/OPERATOR_RUNBOOK.md`.

## Integration preflight

- Added protected `GET /api/preflight` and `backend/preflight.py`.
- Reports presence/absence of operator token, script/voice/render credentials, artifact hostname allowlist, YouTube OAuth/API credentials and writable media directory.
- Does not expose secret values and explicitly reports that configuration presence is not live connectivity verification.
- Dashboard includes an external-integration readiness panel.
- Added unit tests for fail-closed missing configuration and the distinction between configured and live-verified.

## Current validation state — 2026-11-15

Latest run 103 (`43657516480`) still fails before runner allocation: `runner_id=0`, `runner_name` empty and `steps=[]`. The latest commits include API token hardening, safe media staging, approved upload queue, single-page dashboard, Docker path correction, and configuration preflight. They are committed but not runtime-tested. Dashboard and integration preflight are source-level implementation only; browser behavior, external provider execution, OAuth, YouTube upload and revenue reconciliation remain unverified.

- Dashboard financial ledger and profitability scenarios now accept USD, KRW, JPY and GBP independently; reports remain currency-filtered and do not mix exchange rates.

Latest CI run 106: https://github.com/justinhblee-prog/shorts/actions/runs/43657737487. The job again terminated with `runner_id=0`, no runner name and `steps=[]`; no tests executed, including the latest approved-queue filtering change.

## BUILD-00010 — evidence-based performance analysis

- Added per-video measurement status and valid snapshot deltas, grouped by brand and region.
- Detects negative counter differences as reset/invalid measurements and excludes them from growth aggregates.
- Reports measurement coverage and source-grounded operational recommendations; no predictive/causal claims.
- Financial summaries are grouped by brand and ISO currency; optional brand filter applies to both video and financial data. No FX mixing.
- Dashboard displays brand, region, video-level measurement and recorded financial summaries.
- Unit tests cover insufficient snapshots, measured deltas, counter resets, multi-currency separation and brand filtering. Execution remains blocked by Actions runner allocation.

## BUILD-00011 — scheduling and recovery

- Added persistent `schedule_dispatch_outbox` with unique `(schedule_id, scheduled_for)` occurrence keys.
- Due schedule advancement and outbox insertion are atomic under `BEGIN IMMEDIATE`.
- Queue enqueue uses a deterministic idempotency key; if the scheduler crashes after enqueue but before outbox acknowledgement, the next poll replays safely without creating a duplicate job.
- Failed dispatch attempts remain pending with bounded error details and retry on later scheduler polls.
- Added tests for single dispatch, crash-window replay, inactive schedules and timezone-aware scheduling. Runtime execution remains pending due GitHub Actions runner allocation failures.

- Scheduler operations dashboard/API now exposes durable outbox pending/dispatched counts, attempts and bounded last-error details via authenticated `GET /api/schedules/outbox`; pending records are automatically retried by the scheduler loop.

Latest CI validation check: run 114 ([Actions](https://github.com/justinhblee-prog/shorts/actions/runs/43658007033)) failed before runner allocation (`runner_id=0`, empty runner name, zero steps). BUILD-00010 and BUILD-00011 source/tests are committed but not executed by CI.

Latest CI run 115: https://github.com/justinhblee-prog/shorts/actions/runs/43658032770. Job metadata confirms `runner_id=0`, no runner name and `steps=[]`; no tests executed.

## BUILD-00012 — integrated lifecycle validation

- Added an end-to-end contract test covering durable queue submission/claim, script → voice → render provider adapters, artifact persistence, human review approval, allowlisted MP4 staging, private YouTube upload, first metrics snapshot and explicitly recorded financial entries.
- Added a crash-window recovery path: when the queue has durably moved a job to `review_pending` but the process stops before updating `production_runs`, the worker and pending-review API reconcile the production record from the authoritative queue state.
- Added an integration test simulating that exact crash boundary and asserting the job reappears in the review queue.
- All external AI/CDN/YouTube interactions in the new lifecycle test are mocked; this validates state integration only, not live provider connectivity or actual revenue.
- GitHub Actions runner allocation remains blocked; tests have not been executed in CI or a local Python runtime.

Latest BUILD-00012 validation attempt: run 122 (https://github.com/justinhblee-prog/shorts/actions/runs/43658445925) failed before runner allocation (`runner_id=0`, empty runner name, `steps=[]`). The integration tests were not executed. The latest source commit is `2eff2834db260134f97ef72a66f54409e406bfbb`.

Latest test attempt: run 123 (https://github.com/justinhblee-prog/shorts/actions/runs/43658503655) again failed before runner allocation (`runner_id=0`, empty runner name, `steps=[]`). The added negative recovery test is committed but not executed. Latest code/test HEAD: `6a42c46d451218dd24dfd10ab41de7ec7bee0000`.
## YouTube upload ambiguity recovery — 2026-11-15

- Upload attempts now distinguish failures before the remote request starts from uncertain outcomes after the resumable YouTube request begins.
- A network timeout, process interruption surfaced as an exception, or missing final video ID after request start is recorded as `reconciliation_required`; automatic retry is blocked to prevent duplicate uploads.
- Active resumable uploads refresh their local activity timestamp in a background heartbeat and after completed chunks. A still-`uploading` record becomes eligible for manual reconciliation only after `NEXUS_UPLOAD_STALE_SECONDS` (default 900 seconds; minimum 60 seconds).
- Added authenticated `POST /api/youtube/uploads/{job_id}/reconcile`. An operator must explicitly confirm the outcome, provide a YouTube video ID if uploaded, and record a note.
- If the operator verifies a matching private video, the record is finalized against that video ID. If the operator verifies no remote upload exists, the record becomes retryable. No automatic remote retry occurs while the outcome is ambiguous.
- Dashboard approved-upload queue distinguishes active uploads from stale/uncertain uploads and exposes the reconciliation action only when eligible.
- Added unit tests for uncertain timeout, duplicate-retry blocking, both reconciliation outcomes, required evidence note, conflicting decisions and premature reconciliation rejection.
- **Validation status:** source and tests are committed; they have not executed because GitHub Actions runner allocation has repeatedly failed before steps start. No live YouTube upload was performed.

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


## Review/upload state-machine audit — 2026-11-15

- Corrected two YouTube publishing regression tests that referenced a nonexistent self.store fixture; they now use the configured self.uploads store.
- Review decision persistence now checks the affected production-row update count (rowcount) rather than cumulative connection changes, so a decision is accepted only when its guarded state transition actually updates exactly one row.
- These are source-level corrections. Tests have not been executed because no functioning CI runner or local Python runtime is available in this session.


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


### Latest verification checkpoint — 2026-11-15 01:38 UTC

- The targeted local Python/SQLite harness was rerun against the current attempt-aware transition logic. Passed: attempt-start and uncertain-outcome events; operator-confirmed not-uploaded then retry; late old-attempt response quarantine; resolution event attributed to the originating attempt; same-attempt post-confirmation exception remains terminal; preflight failure audit; canonical current-video retention after a late duplicate.
- All nine current audit INSERT SQL shapes were executed against SQLite, including attempt-generation fields. Passed. Legacy schema additive migration and immutable event UPDATE/DELETE triggers also passed. Separate targeted checks passed for review-decision cursor rowcount handling, production-stage cursor rowcount/artifact invalidation behavior, and required late-resolution API video ID validation.
- Latest GitHub Actions run observed: [43664002080](https://github.com/justinhblee-prog/shorts/actions/runs/43664002080), commit `035fcdfab2a9d8a5a1790a8352718d8cf0ecb9f4`. The job completed in ~2 seconds with `runner_id=0`, empty runner name, and no steps. No repository test command ran. The complete pytest suite and live YouTube/OAuth integration remain unverified.
