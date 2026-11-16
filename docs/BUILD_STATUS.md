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
- **Still not validated:** live provider/OAuth/upload behavior, timezone/DST calendar schedules and production alerting. Process supervision and multi-instance scheduler leadership have since received automated regression coverage; see the 2026-11-15 scheduler leader-election checkpoint at the end of this document.

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


### CI recovery and full-suite verification — 2026-11-15 02:00 UTC

- Repository visibility was changed to public and verified through the GitHub repository API. The earlier repeated failures occurred before runner allocation (runner ID 0, no steps); after the visibility change, a rerun obtained a standard GitHub-hosted Ubuntu runner and reached checkout, Python setup, dependency installation and the test command.
- The first real full-suite run exposed test and implementation defects. Corrections included committing SQLite transactions in the scheduler store context manager, fixing API test patch targets to module globals, correcting a ledger ROI expectation, repairing the review-history fixture, and making performance analytics fixtures use the real review-approval flow.
- The final API test patch correction is in commit `022b823334017f33a2924bd671fd976626416172`. GitHub Actions runs #290 and #291 on this exact commit completed successfully. The latest run #292 also completed successfully: [43665563890](https://github.com/justinhblee-prog/shorts/actions/runs/43665563890). The workflow installed dependencies and `sh scripts/validate.sh` passed; log confirms **113 tests** executed.
- This verifies the repository's automated Python validation suite only. It does not validate live AI provider credentials, rendered video quality, OAuth, actual YouTube upload, public publishing, revenue collection, or production deployment.
- PR #3 was subsequently merged into `main`; the follow-on validation fixes and CI checkpoint are on the development branch and should be reconciled with the merged baseline before the next release merge.


### CI green checkpoint — 2026-11-15 02:01 UTC

- GitHub Actions hosted-runner provisioning is now working for this public repository. The latest verified run is [43665751844](https://github.com/justinhblee-prog/shorts/actions/runs/43665751844), head commit `d25da3d23e89731b91721fbe50e5d9822cde4321`; job setup, checkout, Python 3.11, dependency installation, and `sh scripts/validate.sh` all completed successfully.
- The workflow log confirms **113 tests ran** and the job conclusion is `success`. Multiple adjacent runs for the immediately preceding commits also completed successfully.
- Fixes included: scheduler SQLite context manager now commits successful transactions and rolls back exceptions; API security tests patch module-level symbols rather than attributes on the FastAPI app; ledger ROI expectation corrected to the implementation's percentage formula; YouTube review-history fixture models a subsequent revision correctly; performance analytics fixtures now create actual review approval and attempt-aware upload records.
- This green CI result establishes that the committed automated backend validation suite passes. It does not establish live AI provider connectivity, actual voice/video generation, YouTube OAuth or private upload, revenue ingestion, frontend browser QA, or deployment readiness. Those remain explicit integration gates.


### Brand-specific AI production profile propagation — 2026-11-15

- Production submission now snapshots the selected active brand's editorial profile into the durable queue payload: positioning, target audience, tone, risk level and review rules. Later profile edits do not silently rewrite already queued work.
- The worker validates this optional profile before provider calls and forwards it to all three production stages: script receives positioning/audience/tone/risk and explicit editorial constraints; voice receives tone and target audience; rendering receives the full brand profile.
- Added regression tests for provider-stage propagation, malformed-profile fail-closed validation, and API-level profile snapshotting at submission.
- GitHub Actions run [43666178495](https://github.com/justinhblee-prog/shorts/actions/runs/43666178495) on commit `f7d7c20c396d8ea05fb60ed8414b84d5301e63d8` completed successfully. The full validation script passed and the log confirms **116 tests ran**.
- This verifies profile propagation through the mocked provider contract and API test boundary. Actual provider prompt adherence, voice characteristics and rendered visual branding still require live provider credentials and real media review.


## Latest verified checkpoint — 2026-11-15 (UTC)

- GitHub Actions hosted-runner allocation is operational. This checkpoint supersedes the older historical notes in this document that say Actions has never executed the test suite or that runner allocation is still blocked.
- Latest run: https://github.com/justinhblee-prog/shorts/actions/runs/43666742044
- HEAD: `b1db42bc366d1b9c6ddc41e3355c80ed84cc158a`
- Workflow completed successfully. `sh scripts/validate.sh` passed: **118 tests ran, OK**.
- The review queue now returns the frozen `brand_profile` captured in the durable job payload. It exposes positioning, audience, tone, risk level and editorial review rules without exposing the raw queue payload.
- The single-page review workspace displays the brand's risk level and editorial checklist before approval, revision request or rejection. All user-controlled values are HTML-escaped.
- Review listing remains compatible with isolated/legacy databases where the queue table has not yet been initialized; in that case brand guidance is null rather than causing the review endpoint to fail.
- Regression coverage verifies frozen-profile retrieval, old database compatibility, and the frontend's use of the guidance fields.

**Validation boundary:** this confirms the Python suite and source-level frontend assertions. It does not confirm browser interaction in a deployed environment, live AI provider adherence, real audio/video generation, YouTube OAuth/upload, or actual revenue.


### Review usability enhancement — verified 2026-11-15

- Pending review cards now show the actual generated script in an expandable, escaped text preview and provide an inline audio player for the generated narration. The rendered video link remains available.
- This lets the reviewer compare the script, narration and final render before approving, requesting changes or rejecting; it does not bypass the human approval gate.
- `scripts/validate.sh` now runs `node --check ../frontend/app.js` when Node.js is available, in addition to Python compile and unit tests.
- Verified latest source HEAD: `c12300583c6c45b3750eba2ec667027a02628143`.
- GitHub Actions: https://github.com/justinhblee-prog/shorts/actions/runs/43666919957 — success; **118 tests passed** and JavaScript syntax check completed in the validation script.
- Browser-level behavior, external media playback availability, live AI generation and real YouTube upload still require a deployed environment and configured provider credentials.


### Ambiguous production lease expiry — fail-closed recovery — 2026-11-15

- A short-video production worker lease expiry is treated as an ambiguous external side effect, not a safe retry signal. The queue job becomes `failed_terminal`, its production record is synchronized, and the durable production pause is set transactionally.
- Both claim-time lease recovery and explicit `recover()` apply this rule. Non-production queue jobs retain their existing retry policy.
- Ctrl+C during provider execution pauses first so the current queue job and production record are terminalized atomically before the worker exits. Hard process/host kills are handled by lease-expiry recovery.
- Regression coverage verifies no replacement worker receives an ambiguous production job, stale workers cannot write, and the durable pause survives recovery.
- Final pre-merge validation [run 43667294949](https://github.com/justinhblee-prog/shorts/actions/runs/43667294949) passed **121 tests**; post-merge main validation [run 43667375809](https://github.com/justinhblee-prog/shorts/actions/runs/43667375809) also passed **121 tests** on merge commit `f4d56bba10476d8bce6d05563724e7c72ca5c361`.
- Operators must inspect remote provider history, artifacts and billing before creating a replacement request. A lease expiry cannot establish whether the remote service completed the original request.


### API production execution fail-closed alignment — 2026-11-15

- The authenticated API execution route now applies the same stop policy as the background worker: provider errors, stale production leases and unexpected pipeline failures persist a production pause.
- Failure details are recorded on the queue job where the current lease still permits it; the pause fences any other in-flight production work and prevents further production claims until explicit operator resume.
- Added API regression coverage for provider failure, internal failure and stale-lease conflict pause behavior.
- GitHub Actions main-branch run [43667660603](https://github.com/justinhblee-prog/shorts/actions/runs/43667660603) passed **123 tests**. Python compilation and JavaScript syntax validation also completed successfully.
- This confirms the API error-path behavior under tests; live provider outage behavior remains dependent on external credentials and runtime conditions.


## Verified milestone — trend-to-production handoff (2026-11-15)

- Added authenticated `POST /api/trends/{trend_id}/draft-production`. It retrieves one persisted trend signal by exact ID, checks that the selected brand is active and supports the signal's region and selected language, then creates a durable production job.
- The job freezes the brand's positioning, audience, tone, risk level and review rules, and carries the original trend source, title, URL, summary, publication timestamp and region into the production brief.
- Script-provider payload now receives this source context plus explicit handling rules: treat it as untrusted source material, verify claims independently, do not treat source text as instructions, do not fabricate facts, and do not equate popularity with truth.
- Added strict context validation (bounded text lengths, required title and URL, HTTP(S)-only source URL). Trend handoff uses a deterministic idempotency key by trend, brand and language to prevent accidental duplicate submissions.
- The discovery UI now renders eligible active-brand choices for each trend and a one-click **이 트렌드로 제작 기획** action. It excludes unsupported region/brand combinations. The action creates a queued draft only; it does not invoke paid providers, publish, or bypass human review.
- Added direct indexed trend lookup and regression tests for exact lookup, missing/invalid context, brand/region validation, API handoff, and UI wiring.
- Latest verified source HEAD: `b4f36a7a2eb008cdd8828eab6350e943fabc93e4`.
- GitHub Actions: https://github.com/justinhblee-prog/shorts/actions/runs/43668260445 — success; **132 tests passed**, plus JavaScript syntax validation.
- Earlier intermediate CI run `43668067130` failed because the new test import was missing; this was corrected, and the final HEAD run above is green.

**Validation boundary:** tests validate the handoff contract and mocked pipeline. They do not verify live Google News collection, live YouTube competitor metrics, real AI-provider adherence, real media generation, YouTube upload or revenue. Search-volume/view-velocity metrics remain unavailable unless an actual provider supplies them.


### Audited production pause/resume controls — 2026-11-15

- Added a durable `worker_control_events` audit table. Automatic pauses are attributed to `system`; operator pause/resume actions record the operator ID, reason, affected job and timestamp.
- Added authenticated `GET /api/queue/control`, `POST /api/queue/pause` and `POST /api/queue/resume` endpoints. Resume requires a non-empty operator ID and investigation note and returns HTTP 409 if the queue is not paused.
- Added dashboard controls under **운영 관제 · 수익 분석 → 예약·작업 현황**. The UI displays the pause reason and recent audit history, disables invalid actions, and confirms resume after the operator verifies remote provider history, artifacts and billing.
- Regression tests cover persistence and audit ordering, authenticated API behavior, invalid resume attempts, and API error-path pauses.
- GitHub Actions main run [43668403972](https://github.com/justinhblee-prog/shorts/actions/runs/43668403972) passed **133 tests**, including Python compilation and JavaScript syntax validation. Whitespace-only operator IDs and notes are rejected.


### Scheduler pause-aware dispatch — 2026-11-15

- The scheduler now checks the durable production pause before dispatching pending outbox records. While paused, due schedule occurrences remain persisted as pending and no production queue jobs are created.
- After an operator resumes production, pending outbox occurrences replay through the existing deterministic idempotency key; a crash between queue enqueue and outbox acknowledgement remains safe.
- Scheduler logs now include timestamps, severity, actionable exception traces, dispatch counts and an explicit warning when dispatch is held by a production pause.
- Added regression coverage proving a due schedule remains in the outbox during pause, creates no queue job, and dispatches exactly once after audited resume.
- GitHub Actions run [43668701509](https://github.com/justinhblee-prog/shorts/actions/runs/43668701509) passed **137 tests** on commit `77aa3e2fbfd6ed874a55f57d35f17d49b712fb0d`; Python compilation and JavaScript syntax checks also passed.


## Verified milestone — competitor evidence in profitability ranking (2026-11-15)

- Competitor search results now offer **최근 영상 분석**. It fetches and persists up to 20 recent public videos. Operators can select up to 10 channels as comparison evidence.
- Opportunity scoring evaluates stored recent video titles against the opportunity title using transparent token overlap (at least 25% of topic terms), reporting sample count, matched count, median observed views and up to five examples.
- A sample-based competitive-pressure adjustment is applied to the existing 0–100 priority score: `min(10, 10 × matched_videos / (selected_channels × 3))`. It appears as a separate score-breakdown component and does not alter revenue, ROI or margin estimates.
- With no stored samples, no penalty is applied. Results state that selected channels and available recent videos are not a market-wide sample and do not establish growth, causal demand or revenue.
- Added UI selection, API integration and benchmark tests. Also fixed legacy scheduler queue-adapter compatibility exposed by CI.
- Latest verified source HEAD: `eb1a3248ac7429003e3e0f9a024fa02929653a22`.
- GitHub Actions: https://github.com/justinhblee-prog/shorts/actions/runs/43668719310 — success; **137 tests passed**, JavaScript syntax check passed.

**Validation boundary:** scoring and API contracts were tested with stored/mock public-video samples. Live YouTube collection still requires `YOUTUBE_DATA_API_KEY`; live competitor coverage, view velocity, market-wide saturation and actual revenue are not verified.


### Schedule deactivation and pending outbox safety — 2026-11-15

- Deactivating a schedule now atomically cancels all its still-pending outbox occurrences. Re-enabling the schedule does not resurrect those cancelled occurrences; only newly due schedule occurrences are dispatched.
- This closes the case where a due schedule was held during a production pause, then unintentionally dispatched after the operator deactivated it and later resumed production.
- Added regression coverage for pause → due outbox reservation → schedule deactivation → resume, proving no queue job is created.
- GitHub Actions run [43668839781](https://github.com/justinhblee-prog/shorts/actions/runs/43668839781) passed **138 tests** on commit `3a2a0af527dd72b2b92f2f16f2919d30ca0f0216`; Python compilation and JavaScript syntax validation passed.


### Saved opportunity ranking UI — verified 2026-11-15

- The intelligence workspace now fetches and displays the 20 highest-ranked saved opportunity evaluations from `GET /api/opportunities`.
- Each row shows rank, title, priority score, estimated net-profit range, competitor adjustment, sample counts and timestamp. The list refreshes after scoring and via a manual refresh control.
- This is an estimate/ranking view only. It does not represent actual earnings, guaranteed performance or a market-wide competitive assessment.
- Latest source HEAD: `0b32d5ca12aea5c2580264665c4fd3d7cbfe7cf0`. GitHub Actions: https://github.com/justinhblee-prog/shorts/actions/runs/43668889808 — success; **139 tests passed**, including JavaScript syntax validation.


### Scheduler crash-after-enqueue replay — 2026-11-15

- Added a regression test for the critical outbox window where the durable job queue accepts a scheduled job but the scheduler crashes before acknowledging the outbox record.
- On replay, the scheduler sends the same deterministic idempotency key; the queue returns the existing job and the outbox becomes dispatched without creating a duplicate.
- GitHub Actions run [43668945402](https://github.com/justinhblee-prog/shorts/actions/runs/43668945402) passed **140 tests** on commit `d69556f08da4acb7c4306cc81535f3c91c8e0d8a`; Python compilation and JavaScript syntax validation passed.


### Worker liveness visibility — 2026-11-15

- Added a dedicated worker registry heartbeat updated every worker polling cycle, including idle and production-paused periods. Worker presence no longer depends on having a currently leased job.
- Worker listings now compute stale records as `offline` after the configured lease window (minimum 30 seconds), rather than displaying a dead process as online indefinitely.
- Added regression coverage for idle worker registration, heartbeat refresh and stale-to-offline detection.
- GitHub Actions run [43669105872](https://github.com/justinhblee-prog/shorts/actions/runs/43669105872) passed **141 tests** on commit `e4f64cbd78e542165c545dcf8b659d8915eb77f2`; Python compilation and JavaScript syntax validation passed.


## BUILD-00013 — evidence-bounded trend-to-brand recommendations

- Added `backend/trend_recommendations.py` to rank collected trend signals using recency (0–40) and editorial brand fit (0–40).
- Active brand profiles are matched by title/summary token overlap; incompatible regional profiles are excluded. The endpoint returns up to three suitable brand candidates per trend.
- Added authenticated GET `/api/trends/recommendations?region=US&limit=30`.
- The score is explicitly an editorial discovery signal, **not** a profitability forecast. The remaining 20 score points are intentionally unallocated because the current trend feeds do not supply comparable search volume, Shorts demand, verified RPM, or production cost.
- Each result carries evidence-gap flags. No trend is automatically sent to production; the operator still selects a brand and uses the existing draft-production and human-review gates.
- Regression tests cover freshness ordering, region eligibility, missing brand matches, evidence caveats and route authentication.
- **Validation:** GitHub Actions run `43669583140` completed successfully at source commit `8efee96c92fc4e9102512513bb04fc9ae2c44335`; `149` tests passed, including ranking, authenticated API and frontend integration regressions. Earlier failed runs exposed a region-eligibility edge case and literal-newline formatting errors; both were corrected before this successful run.


### Faster production lease-loss detection — 2026-11-15

- Reduced the default active-job heartbeat interval from one-third of the lease (100 seconds for a 300-second lease) to **10 seconds**, configurable through `NEXUS_HEARTBEAT_SECONDS` and capped at one-third of the lease.
- This reduces the delay before a worker detects an operator pause or lease revocation. An in-flight provider HTTP request cannot be forcibly cancelled by the current synchronous transport; it runs until its configured timeout, after which the stop signal prevents the next pipeline stage.
- Extracted the heartbeat interval policy into a pure helper and added boundary tests for the lease cap and minimum interval.
- GitHub Actions run [43669352365](https://github.com/justinhblee-prog/shorts/actions/runs/43669352365) passed **148 tests** on commit `5b1aa3d0d1993176c4d135abf581e101f3113efe`; Python compilation and JavaScript syntax validation passed.


### Dashboard integration

- Added a brand recommendation panel to the global intelligence workspace. It refreshes for the selected market and shows freshness, editorial-fit score, top brand candidate and missing-evidence caveat.
- Operators can select one of the region/language-compatible suggested brands and create a production draft. This still uses the existing authenticated draft endpoint and human review gate; it does not auto-generate or publish.
- Frontend static syntax check and complete regression suite passed in the validation run above.


### Frontend validation gate restored — 2026-11-15

- Found that CI watched backend and validation-script paths but ignored frontend-only changes. A trend dashboard update therefore introduced a literal newline escape in `frontend/app.js` without triggering the syntax check.
- Fixed both stray literal newline escapes and expanded workflow path filters to include `frontend/**`. Frontend JavaScript changes now trigger the same automated validation workflow.
- GitHub Actions run [43669577773](https://github.com/justinhblee-prog/shorts/actions/runs/43669577773) passed **149 tests** and the frontend `node --check` step on commit `8970caef75930c00be4b6125455daa8639ccd10e`.


### Static dashboard DOM consistency validation — 2026-11-15

- Added `scripts/check_frontend_ids.py` to detect duplicate HTML IDs and literal JavaScript `$("id")` selectors that do not exist in `frontend/index.html`.
- Integrated the check into `scripts/validate.sh` alongside Python compilation, JavaScript syntax checking and the unittest suite.
- CI path filters now include all `frontend/**` and `scripts/**` changes, so dashboard and validation-tool changes cannot silently bypass the workflow.
- GitHub Actions run [43669754936](https://github.com/justinhblee-prog/shorts/actions/runs/43669754936) passed **149 tests**, JavaScript syntax checking and the new frontend ID validator.


### CI path-filter parity for push and pull requests — 2026-11-15

- The initial DOM-validation integration expanded push path filters to `scripts/**`, but the pull-request filter still listed only `scripts/validate.sh`. That left changes to other validation scripts able to bypass pull-request CI.
- Updated both push and pull-request filters to cover `backend/**`, `frontend/**`, `scripts/**` and the workflow file.
- Verified GitHub Actions run [43669862254](https://github.com/justinhblee-prog/shorts/actions/runs/43669862254) on commit `6b8807068363dcb6fb639b4c1c0b5e4643b3e8aa`: success, **149 tests passed**, JavaScript syntax validation passed, and the DOM validator reported **84 unique HTML IDs / 69 literal selectors**.
- This validates the repository's automated checks only; live YouTube OAuth/upload, external AI rendering and real financial ingestion remain unverified.


### Graceful container termination during production — 2026-11-15

- Added SIGTERM handling for the production worker. If a process receives termination while holding a production lease, it signals the pipeline stop event and durably pauses production, terminalizing the current/other in-flight production jobs rather than waiting for lease expiry.
- Started the job heartbeat before post-claim production-row reconciliation so a termination signal during that reconciliation window is also fenced before any provider request can begin.
- Corrected the paused-worker loop to check the stop flag before sleeping, allowing a terminated worker to exit even when production is already paused.
- Added tests for signal-driven pause and for local stop behavior when pause persistence itself fails.
- GitHub Actions run [43669995888](https://github.com/justinhblee-prog/shorts/actions/runs/43669995888) passed **151 tests**, frontend syntax and DOM ID checks, and Python compilation.


### Region-scoped competitor evidence retrieval — 2026-11-15

- Corrected trend recommendations so competitor video samples are fetched only for channels eligible for each trend's region, with per-channel caching to avoid duplicate reads across trends.
- This prevents irrelevant regions from being queried and fixes a regression where the test expected one regional channel but the implementation queried both US and JP channels.
- GitHub Actions run [43670180646](https://github.com/justinhblee-prog/shorts/actions/runs/43670180646) passed **152 tests**, frontend syntax/DOM validation and Python compilation on commit `82263617c14f7c2fe6ace864cf5510a0d66fe21d`.


### Region-scoped competitor evidence in trend recommendations — 2026-11-15

- Reused the existing stored YouTube competitor-channel/video sample to attach an evidence summary to each trend recommendation: selected channels, observed video count, topic-matched count, median observed views and up to five examples.
- Competitor samples are restricted to the trend's region (or all stored regions for GLOBAL/unscoped trends), with at most 10 recently collected channels and 30 stored videos per channel. The retrieval now avoids querying unrelated regions.
- The evidence is display-only and does **not** alter the editorial recommendation score. It is not market-wide demand, saturation, view velocity, search volume or revenue. Missing samples are explicitly represented in `evidence_gaps`.
- Dashboard recommendation cards now show observed competitor sample counts and median views, with a caveat explaining the sample boundary.
- Initial regression test failed because the test expected only one channel fetch while the implementation preloaded two regions; retrieval was then narrowed to trend-eligible regions. The corrected GitHub Actions run [43670200759](https://github.com/justinhblee-prog/shorts/actions/runs/43670200759) passed **152 tests**, including frontend syntax and DOM ID validation.
- Actual YouTube Data API credentials/live data remain unverified; this feature only summarizes records already stored from prior competitor collection.


### Docker shutdown grace and deployment validation — 2026-11-15

- Added `NEXUS_HEARTBEAT_SECONDS=10` to `.env.example` so the active worker lease detection interval is configurable without editing source.
- Added a 45-second Docker Compose `stop_grace_period` for the production worker, allowing its SIGTERM handler to persist the production pause before Docker forcibly terminates the container.
- Extended `scripts/validate.sh` to parse `compose.yaml` with PyYAML, catching malformed deployment configuration in CI.
- GitHub Actions run [43670349660](https://github.com/justinhblee-prog/shorts/actions/runs/43670349660) passed **152 tests**, Python compilation, frontend JavaScript syntax/DOM ID checks, and Docker Compose YAML parsing.


### Multi-instance scheduler leader election — 2026-11-15

- Added a singleton scheduler leader-lease table to the shared SQLite database. A process acquires a unique fencing token; a live lease prevents another process from dispatching, and an expired lease can be taken over after a crash.
- Lease renewal is checked before each outbox dispatch, and the lease token is checked again before marking an outbox item dispatched. A stale scheduler cannot renew or release a newer owner's lease.
- The existing outbox and deterministic queue idempotency key remain the final duplicate-dispatch protection if a process dies after enqueue but before recording the outbox completion.
- Added regression coverage for competing owners, expiry/takeover, stale-owner fencing, invalid lease rejection and successful dispatch under a valid lease.
- GitHub Actions run [43670844206](https://github.com/justinhblee-prog/shorts/actions/runs/43670844206) passed **156 tests** on commit `851551896e1bc1b0416427d3a4d6f5964f05862c`. Python compilation, frontend JavaScript syntax/DOM ID checks and Docker Compose YAML parsing also passed.
- Calendar/DST recurrence rules and multi-host database deployment remain outside the current SQLite baseline.


## Platform policy preflight and review visibility — 2026-11-15

- Added `backend/policy_engine.py` with a versioned, deterministic YouTube/TikTok pre-production risk screen. It checks explicit high-risk flags, declared visual/audio/likeness rights, synthetic-media status and disclosure acknowledgement, factual-claim verification, originality notes and target platforms.
- Explicitly declared unauthorized assets, non-consensual likeness, deceptive impersonation, prohibited content, fake engagement/platform evasion, or denied asset rights produce a hard `blocked` result before queue submission. Directly enqueued jobs are also stopped before the first provider call; only that job is terminalized, without globally pausing unrelated production workers.
- Missing declarations remain `review_required`; complete declarations advance only to `ready_for_human_review`, never to a claim of platform compliance or approval. The report is attached to the generated script artifact and passed to the script provider with originality, rights, factuality and anti-manipulation constraints.
- Review workspace displays policy status, blocking reasons, missing confirmations and an explicit limitation notice. Human review and explicit approval remain mandatory before upload.
- Added regression coverage for policy decisions, blocked queue submissions, direct-worker blocking, provider prompt context and review UI visibility.
- GitHub Actions run [43671183060](https://github.com/justinhblee-prog/shorts/actions/runs/43671183060) passed **166 tests** on commit `57878e3b99e03bc1e1e420c600e68d27f9b161e2`; Python compilation, frontend syntax/DOM checks and Compose YAML validation passed.
- **Validation boundary:** this is a deterministic preflight and metadata-driven checklist, not frame-by-frame audiovisual moderation, legal advice, platform approval, monetization eligibility or a guarantee against enforcement. Platform-specific rule packs and live policy refresh, actual rights evidence verification, media-content scanning and upload-time disclosure enforcement remain future work.


## Weighted and explainable brand relevance — 2026-11-15

- Replaced the flat token-overlap brand-fit heuristic in `backend/trend_recommendations.py` with weighted profile-term coverage. Explicit `keywords` and the brand's vertical carry the highest weight, positioning is secondary, brand name is supporting evidence, and broad audience wording has deliberately low weight.
- Added optional `exclude_keywords`; a trend matching an explicit exclusion is not recommended for that brand even if other terms overlap.
- Each brand candidate now exposes matched terms, exclusion matches, and `match_method=weighted_profile_term_coverage` so operators can inspect why a brand was selected. Existing profiles remain compatible when optional keyword fields are absent.
- The ranking remains an editorial relevance signal, not a demand, virality, monetization or revenue forecast. Freshness, source provenance and topic distinctiveness remain separately visible.
- Added regression tests for weighted relevance, explainable match terms and explicit exclusions. CI runs [43671711293](https://github.com/justinhblee-prog/shorts/actions/runs/43671711293) and [43671727149](https://github.com/justinhblee-prog/shorts/actions/runs/43671727149) were triggered for the two source/test commits; validation result is pending at the time of this note.


### Curated brand taxonomy for recommendation ranking — verified 2026-11-15

- Added focused topic keywords to all ten brand profiles so the recommendation engine can distinguish editorial domains more accurately than generic positioning/audience text alone.
- Existing profile rows receive missing default taxonomy fields at startup; operator-customized positioning, custom fields, existing keywords and activation state are preserved.
- Added migration regression tests proving the taxonomy is populated and operator customization survives upgrade.
- Weighted brand-fit scoring now uses explicit keywords and vertical at highest weight, positioning next, brand name as supporting context and broad audience wording at low weight. Explicit exclude_keywords suppresses a brand match.
- Candidate output includes matched terms and the scoring method for auditability.
- GitHub Actions run [43671850512](https://github.com/justinhblee-prog/shorts/actions/runs/43671850512) passed **172 tests** on source commit `7a2c1a3e7a36e3fe13fd7e3754fe2eddd4a2719a`, including Python compilation, frontend syntax/DOM validation and Compose YAML parsing.
- **Boundary:** this improves editorial topic-to-brand relevance; it is not a trained semantic model and does not predict views, virality, watch time, platform recommendation outcomes or revenue. Actual channel performance feedback remains the next major ranking input.

 
### Automated YouTube counter collection and normalized performance signals — 2026-11-15

- Added `backend/metrics_collector.py` as a dedicated periodic service. It runs independently of production workers, refreshes at most 50 due videos in one YouTube Data API v3 `videos.list` request, and defaults to a six-hour interval.
- Added a SQLite-backed singleton collector lease so duplicate collector processes do not normally spend quota concurrently. Due selection skips videos with a recent snapshot; batch size is capped at the API limit of 50.
- Added the `metrics-collector` service to `compose.yaml`, sharing the existing durable database volume and environment credentials. Provider/auth failures are logged and retried on the next interval; they do not pause production.
- Added normalized snapshot-derived `views_per_hour`, elapsed interval, interaction delta and interactions per 1,000 gained views. Negative like/comment counter differences are treated as missing evidence, not negative engagement.
- Added explicit limitations: these Data API counters do not provide average view duration, audience retention, viewed-versus-swiped-away, subscriber conversion or satisfaction. Those require eligible YouTube Analytics data and appropriate OAuth authorization; no such metrics are fabricated.
- Added tests for collector singleton lease, due-video filtering, one-request multi-video refresh, rate normalization and counter reset handling.
- GitHub Actions run [43672298086](https://github.com/justinhblee-prog/shorts/actions/runs/43672298086) passed **178 tests** on commit `4d4fcde7f4571cd69d0997da1acd580dfad10554`; frontend validation passed (84 unique IDs, 69 literal selectors), and Compose YAML validation passed.
- **Not yet live-validated:** actual OAuth credentials, YouTube API quota consumption, production container startup and real channel counter collection. These remain unverified until deployed with valid credentials.

 
### Historical performance feedback wired into recommendation workspace — 2026-11-15

- `PerformanceAnalyzer` now reports brand-level median observed views-per-hour and median interactions per 1,000 gained views, with explicit sample counts. These are derived only from valid stored YouTube Data API counter snapshots.
- The trend recommendation endpoint now attaches each candidate brand's historical performance context. The dashboard shows the measured sample count and observed rates alongside the editorial recommendation.
- **No premature score adjustment:** brand-level performance is not topic-matched and can be confounded by publication age, packaging and audience differences. It is displayed for operator context only; `ranking_score_adjustment=0` until comparable topic-level evidence and a sufficient sample exist.
- Corrected the dashboard score display from `/80` to `/100` and aligned the API method description with the implemented 100-point rubric: freshness 40, editorial brand fit 40, source provenance completeness 10, topic distinctiveness 10.
- Added tests for the performance context, no-score-adjustment guarantee and endpoint integration.
- GitHub Actions run [43672582331](https://github.com/justinhblee-prog/shorts/actions/runs/43672582331) passed **179 tests** on source commit `3d52e5d713967d419c5c7f6fbdceadd83557c2f9`; frontend validation passed (84 unique IDs, 69 literal selectors), and Compose YAML validation passed.
- This remains historical brand-level context, not a prediction of a specific trend's results. Topic-level performance learning is a separate next step.

 
### Topic-matched historical performance evidence — verified 2026-11-15

- Recommendation candidates now include historical production videos from the same brand and target region whose recorded topic overlaps the proposed trend title/summary by at least 25%.
- Only videos with valid snapshot-derived `views_per_hour` are eligible. The context reports matched video count, median views/hour and median interaction rate where available.
- Fewer than three matching measured videos are explicitly marked as limited evidence. The evidence is displayed in the recommendation workspace but does **not** change the recommendation score (`ranking_score_adjustment=0`); this avoids overfitting sparse, non-comparable samples.
- Added regression tests for region isolation, topic matching, median calculations, no-score-adjustment and API wiring.
- GitHub Actions run [43672849832](https://github.com/justinhblee-prog/shorts/actions/runs/43672849832) passed **180 tests** on commit `6a023c5fa39081bdaf83d9c1c663337e4e422aeb`; frontend ID validation passed (84 unique IDs, 69 literal selectors).
- Next learning milestone: establish comparable cohorts by region, publication-age window, format and topic, then validate a score adjustment against held-out historical outcomes before using it to reorder recommendations.


### Platform-specific disclosure and evidence gates — 2026-11-15

- Upgraded the policy pack to `2026-11-15.2` and added official YouTube/TikTok source references for spam/fake engagement, inauthentic/reused content, realistic synthetic-media disclosure, advertiser suitability and TikTok AI-generated content.
- Realistic AI-generated/altered content now requires a separate disclosure acknowledgement for every selected platform: YouTube altered-content disclosure and TikTok AI-generated-content label. A generic acknowledgement is no longer sufficient.
- Added explicit elevated-risk declarations for health/medical claims, financial/investment claims, news/current events, third-party clips/music, reused/compiled material, repetitive/mass-produced formats, sponsorship/affiliate content, minors, regulated goods/services and sensitive personal data.
- High-impact health/financial claims require evidence notes; news/current-events claims require HTTPS source URLs; reused/repetitive material requires a documented transformative contribution; sponsorship and minors require additional declarations.
- Added non-overridable approval blockers for uncleared visual/audio/likeness rights, unknown synthetic-media status, and missing platform-specific realistic-AI disclosures. A reviewer comment cannot bypass these blockers.
- The review report now carries source references, risk assessments, evidence-presence flags, policy version and limitations.
- Added `docs/PLATFORM_POLICY_MATRIX.md` as the source register, decision matrix, data contract and limitation record.
- **Important boundary:** the policy gate reads operator declarations; it does not inspect video/audio bytes or independently prove rights. Platform disclosure acknowledgements do not apply platform labels automatically. YouTube upload remains private-only and requires human approval; public publishing remains disabled.
- CI validation for this branch is pending; do not mark this milestone verified until the branch workflow passes.


- Added authenticated `POST /api/review/{job_id}/policy-evidence` so a reviewer can resolve required attestations during `review_pending` without changing the generated media. The server recomputes the report from the durable queue payload, updates the script artifact metadata, and records append-only `policy_evidence_events`.
- Added a review-workspace action for rights, synthetic-media classification, factuality and platform disclosure attestations. The UI shows non-overridable approval blockers and disables approval until they are resolved.
- Evidence updates are allowed only while both the production record and durable queue job are in `review_pending`; the endpoint rejects stale/terminal jobs and unsupported declaration fields.


### Comparable historical performance cohorts — 2026-11-15

- Extended `GET /api/performance/insights` with measured-video cohorts grouped by region, publication-age bucket at the latest stored snapshot, render-duration bucket, format, and exact normalized topic-token signature.
- Cohort outputs include sample count, median observed views/hour, median interactions per 1,000 gained views, and an explicit evidence status. Fewer than three measured videos are marked `limited`.
- Render duration is read from the stored rendering artifact metadata. Format uses provider-returned format/aspect ratio when available; otherwise it is labeled `vertical_short_requested`, not misrepresented as verified rendered dimensions.
- Topic grouping is lexical and exact-signature based, not semantic clustering. The method and its limitations are returned by the API.
- Added the cohort section to the performance insights workspace.
- Cohort metrics remain display-only with `ranking_score_adjustment=0`. They must not reorder recommendations until a held-out evaluation demonstrates stable improvement against a baseline.

- Cohort identity also includes brand, preventing one channel/brand's historical performance from contaminating another brand's comparison.


### Comparable cohort context in trend recommendations — 2026-11-15

- The trend recommendation endpoint now passes measured performance cohorts into the ranker.
- Each brand candidate exposes up to five same-brand, same-region, lexical-topic-matched vertical-Short cohorts, including publication-age and duration buckets, sample counts, and observed median rates.
- Other brands and other regions are excluded. Nonmatching topic signatures are excluded.
- Cohort context is displayed in the recommendation workspace beside existing brand-level and topic-level history.
- **No score adjustment:** `ranking_score_adjustment=0`; the 100-point editorial rubric remains unchanged until a held-out evaluation validates a stable ranking improvement.


### Recommendation outcome capture and chronological holdout diagnostics — 2026-11-15

- Added `backend/recommendation_evaluation.py` with durable recommendation-run and candidate records. Each recommendation API response stores the returned trend rank, editorial score, selected best-brand identity, score breakdown, and contemporaneous cohort context.
- When an operator submits a trend candidate for production, the API links that production job to the most recent matching recommendation record. No production job is created automatically by this capture mechanism.
- Added authenticated `GET /api/recommendations/evaluation`. It joins selected production jobs to valid snapshot-derived measured video outcomes and reports a chronological pre-holdout/holdout split plus Spearman rank association between the editorial score and observed views/hour.
- Minimum diagnostic threshold is 10 distinct selected and measured production jobs; the holdout contains at least five observations. Sparse samples or constant ranks remain inconclusive.
- The dashboard now displays measured/selected counts, pre-holdout and holdout sizes, and holdout score/outcome association.
- **Strict interpretation boundary:** this is an observational diagnostic among recommendations that operators actually selected for production. It does not observe unseen candidates, correct selection bias, establish causality, or validate a new score adjustment. It is not model training. `ranking_score_adjustment_enabled=false` remains enforced.
- Recommendation API retrievals are stored as candidate snapshots, not proof that a human viewed a card. Actual UI impression tracking and randomized exploration remain future work.
- CI validation pending on this branch; do not mark verified until GitHub Actions passes.

- Repeated identical recommendation responses within 60 seconds reuse the same snapshot run to avoid noisy duplicate records. Unselected candidate snapshots older than 180 days are pruned; selected production-linked evidence is retained for longitudinal diagnostics.


### Production artifact metadata quality gate — 2026-11-15

- Added `backend/production_quality.py` and run it after the renderer returns a video artifact but before the production job can enter `review_pending`.
- Checks script length, provider-attested fact-check/source metadata, voice duration, render duration, reported aspect ratio/dimensions, audio-track presence, subtitle status and voice/video duration mismatch.
- Explicit known non-vertical output, a reported missing audio track, or a reported duration over 180 seconds blocks the production handoff. Missing metadata produces a visible `review_required` warning rather than fabricated success.
- Persists a `quality_check` report artifact and shows blockers/warnings and verification limitations in the human review workspace. Human approval remains mandatory; no score changes or public publication are enabled.
- **Boundary:** the gate evaluates provider-returned metadata and basic script length only. It does not download or inspect media bytes, verify captions, prove factual accuracy or rights, assess visual quality, or establish platform compliance. Provider attestations are not independent verification.
- CI validation pending on this branch; do not mark verified until GitHub Actions passes.

- Approval enforcement is server-side: quality blockers cannot be overridden by a reviewer comment, and `review_required` warnings require an explicit reviewer confirmation note. The review UI requests that note and displays the recorded quality report.


### Recommendation exposure capture uses explicit POST — 2026-11-15

- Kept `GET /api/trends/recommendations` read-only.
- Added `POST /api/trends/recommendations/snapshot` for the production workspace to explicitly capture the candidate set it receives for later outcome linkage.
- Updated the workspace to call the POST endpoint. Identical snapshots remain deduplicated within 60 seconds.


### BUILD-00014 — byte-level rendered media quality gate (2026-11-15)

- Added `backend/media_inspection.py`: invokes ffprobe against a staged local MP4 and parses actual container/stream metadata: format, duration, byte size, video dimensions/codec, audio presence/codec, and subtitle-stream presence.
- Hardened invocation with a bounded timeout, no stdin, and `-protocol_whitelist file,pipe`; rejects symlink input, malformed probe output, missing video stream, non-MP4-family containers, and invalid dimensions/duration/size.
- `ProductionPipeline` automatically stages and inspects renderer output before it can become review-pending whenever `RENDER_ARTIFACT_HOSTS` is configured. It reuses the existing allowlisted HTTPS downloader with DNS public-IP validation, pinned TLS host, redirect rejection and a 256 MiB default cap.
- A byte-level report is attached to the quality-check artifact. Actual non-9:16 dimensions, missing audio, invalid probe, or duration over 180 seconds blocks handoff even if renderer-supplied metadata claims otherwise.
- Added ffmpeg/ffprobe to the production Docker image. The manual stage-media endpoint reuses the already-staged file.
- **Configuration:** set `RENDER_ARTIFACT_HOSTS` to the exact comma-separated renderer artifact hostnames in `.env`. If unset, the pipeline deliberately remains in `review_required` with `actual_media_bytes_not_inspected`; it does not claim byte-level QA.
- **Verification boundary:** ffprobe does not prove visual quality, subtitle legibility/correctness (especially burned-in captions), source facts, copyright/music rights, consent, platform compliance, or monetization eligibility. Human review remains mandatory. The tests use mocked ffprobe output and fake staged media; no real renderer artifact has yet been inspected.


### BUILD-00015 — black-frame and audio-silence signal checks (2026-11-15)

- Extended ffmpeg inspection to scan the full staged video stream with `blackdetect` and the audio stream with `silencedetect`.
- Reports black segments and low-volume silence segments, with warnings for extended black frames, extended silence, and long silence at the beginning/end.
- These are review warnings, not automatic blockers: dark scenes and pauses can be intentional. They are not semantic visual QA, speech recognition, loudness normalization, copyright/music detection, or subtitle correctness checks.
- The human review UI shows actual dimensions, duration, codecs, subtitle stream presence, and black/silence segment counts.
- Analysis uses bounded execution time and a local-file-only protocol whitelist. No media is uploaded to a third-party inspection service.
- Validation pending on this branch; the prior BUILD-00014 baseline passed 210 tests before this extension.


### BUILD-00016 — historical script originality similarity check (2026-11-15)

- Before voice generation, compare the new script against up to 500 prior completed/reviewed scripts in the same language across the ten-brand portfolio.
- Uses normalized token-sequence exact matching and 5-token shingle Jaccard similarity; threshold 0.82.
- Stores an `originality_check` report artifact and includes matching brand/topic/job references in the quality report and review UI.
- Similarity is a reviewer warning, not an automatic rejection. Topic overlap/common phrasing can cause false positives; substantial paraphrasing can evade detection.
- This is not a copyright check, plagiarism verdict, reused-content policy determination, or guarantee of monetization eligibility.
- No generated script is automatically published; human review and approval remain required.
- Validation pending on this branch.


### BUILD-00017 — independent narration transcription and script alignment (2026-11-15)

- Added `backend/speech_alignment.py` to compare a normalized ASR transcript with the exact generated script using token-level Levenshtein distance and word error rate (WER).
- When `TRANSCRIPTION_PROVIDER_URL` is explicitly configured, the pipeline sends the generated audio URL and language to that provider for verbatim transcription before rendering.
- Stores a `speech_alignment` report artifact and adds the result to the production quality report and human review UI.
- WER above 0.25 is a reviewer warning, not an automatic rejection. Short transcripts are marked insufficient rather than falsely passing.
- If no ASR provider is configured, quality reports explicitly include `speech_transcription_not_configured`.
- Configuration is opt-in through `.env`; the audio URL is shared with the configured transcription provider. No ASR provider is called by default.
- This validates approximate spoken narration/script alignment only. It does not verify burned-in subtitles, subtitle timing, factual correctness, pronunciation quality, voice identity consent, or platform policy compliance.
- CI validation pending on this branch.


### BUILD-00018 — extractable subtitle text and script/audio alignment (2026-11-15)

- FFprobe inspection now detects actual text subtitle streams in staged renderer output.
- FFmpeg extracts the first subtitle stream to SRT using a 2 MiB output cap and bounded timeout; extraction failures are recorded as review warnings, not silent success.
- Extracted caption text is compared against independent ASR transcript when configured, otherwise against the generated script, using the same normalized token WER metric (0.25 threshold).
- Persists a `caption_alignment` report artifact and shows status/match estimate in the review workspace.
- Caption mismatch, absent text subtitle stream, truncated/empty extraction or extraction errors require human review; they do not automatically reject the video.
- No text subtitle stream does not prove captions are absent because captions may be burned in. Burned-in caption OCR, timing, placement, font size, contrast, legibility and factual correctness remain unverified.
- Raw extracted subtitle text is not copied into the quality report; only comparison metadata is retained.
- CI validation pending on this branch.


### BUILD-00019 — subtitle timing and reading-speed quality signals (2026-11-15)

- Analyze extracted SRT timecodes for invalid/nonpositive durations, overlapping cues, gaps longer than five seconds, cues shorter than 0.5 seconds or longer than seven seconds, and character rates above 20 characters/second.
- Store timing counts and warning codes in the caption quality report and display them in the human review panel.
- Bound analysis to 10,000 subtitle cues and preserve raw subtitle text out of quality artifacts.
- Timing and reading-speed thresholds are heuristic review signals, not universal platform/accessibility standards. They do not evaluate actual font size, contrast, placement, safe areas, language-specific reading speed, or burned-in captions.
- Validation pending on this branch.


### BUILD-00020 — within-exposure recommendation validation (2026-11-15)

- Extended recommendation evaluation to compare only candidates from the same captured recommendation exposure and same measured outcome cohort: brand, region, publication-age bucket, duration bucket and format.
- Requires at least three selected measured outcomes per comparable cohort and at least five eligible exposure runs before reporting a chronological 70/30 holdout.
- Summarizes cohort Spearman correlations within each exposure run, then reports median score/rank association and positive-association share across holdout runs.
- Retains the pooled cross-exposure metric only as a coarse diagnostic and explicitly labels its confounding boundary.
- Dashboard now shows within-exposure holdout coverage separately from pooled correlation.
- Recommendation score changes remain disabled. The evaluation is observational and selection-biased because only operator-selected recommendations receive production outcomes.
- CI validation pending on this branch.


### BUILD-00021 — upload-time policy version freshness gate (2026-11-15)

- Before a YouTube upload attempt is initialized, verify the current script artifact contains the active policy rule version and has no unresolved policy blockers.
- Verify the latest human approval snapshot was made against the same active policy version; old approvals cannot silently carry forward after a rule update.
- Missing/malformed policy evidence, stale approval version, blocked status or approval blockers stop upload before the remote YouTube API request.
- Existing private-only upload behavior and explicit human approval remain unchanged.
- This compares local rule versions only; it does not live-refresh Google/TikTok policy documents. Current official rules and regional restrictions still require manual verification.
- CI validation pending on this branch.


### BUILD-00022 — upload policy-version audit stamps (2026-11-15)

- Persist the active `POLICY_VERSION` and `POLICY_CHECKED_ON` on each YouTube upload record at attempt creation.
- Stamp the same values into the immutable `upload_attempt_started` event so the audit trail preserves the exact local policy ruleset used.
- Additive SQLite migrations extend existing upload and event tables without rewriting historical records; legacy rows retain null policy stamps.
- CI validation pending on this branch.


### BUILD-00023 — enforce policy check-date freshness at upload (2026-11-16)

- Require both the current script policy preflight and the latest human-approved script snapshot to match the active `POLICY_VERSION` and `POLICY_CHECKED_ON` before an upload attempt is initialized.
- Reject missing or stale check dates before any remote YouTube API call; do not stamp incomplete policy evidence into upload audit records.
- Add regression tests for stale current evidence and stale approval snapshots.
- GitHub Actions PR run [43779365868](https://github.com/justinhblee-prog/shorts/actions/runs/43779365868) passed: **247 backend tests** and `scripts/validate.sh` completed successfully. PR #80 was squash-merged into `main` as `5dba9163a20e8fbc4e68bca260c962f944500b0a`. The CI run executed on the PR head before the squash merge; the merge commit itself has no separate CI run recorded.


### BUILD-00024 — invalidate approval when production artifacts change (2026-11-16)

- Before initializing a YouTube upload, compare the complete latest human-approved artifact snapshot with the current ordered production artifact set.
- Compare stage, artifact type, artifact URL and parsed metadata; reject additions, removals, reorderings, malformed metadata or modifications after approval.
- Keep policy version/date freshness checks as an additional independent gate.
- Add regression tests for post-approval artifact modification and artifact addition. Validation pending on this branch.


### BUILD-00025 — bind YouTube upload bytes to human approval (2026-11-16)

- Compute a streaming SHA-256 digest and byte length when renderer media is staged.
- Persist the fingerprint in rendering artifact metadata so it is included in the immutable human approval snapshot.
- At upload, require the staged filename, byte length and SHA-256 to match the approved snapshot; copy verified bytes through a no-follow file descriptor into a private temporary snapshot and upload only that immutable copy.
- Remove the temporary snapshot after success or failure. Manual staging persists the fingerprint and returns the production run to review_pending when the fingerprint changes, requiring fresh human approval.
- Regression tests cover staged-media mutation, mismatched path and SHA-256 capture. GitHub Actions run [43780616121](https://github.com/justinhblee-prog/shorts/actions/runs/43780616121) passed **252 backend tests** and `scripts/validate.sh`. PR #83 was squash-merged into `main` as `26fcc66b2fe59cfa5521db0f02b34554bdd34259`.


### BUILD-00026 — TikTok prohibited-AIGC policy guardrails (2026-11-16)

- Refresh the local policy pack to `2026-11-16.1` after checking current official YouTube and TikTok policy references.
- Add explicit non-overridable TikTok flags for AI-generated likenesses of minors, private adults without permission, fake authoritative/crisis content, and false public-figure endorsements.
- Expose `policy_flags` in the human policy-evidence API and allow the review store to merge/persist these declarations.
- Add regression tests for the policy engine, API model and review-store evidence update. CI validation pending.
