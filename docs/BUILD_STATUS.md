# NEXUS STUDIO PRO — Development Status

**Baseline:** v0.1  
**Repository:** https://github.com/justinhblee-prog/shorts  
**Updated:** 2026-11-17

## Business objective

Automate a profitable short-form video operation: global topic discovery → evidence-backed opportunity scoring → script/voice/video production → human review → publishing → measured revenue and cost analysis → strategy improvement.

Business success is measured by verified net revenue, ROI, content throughput, and operating cost. Forecasts remain estimates. Public publishing requires explicit human approval.

## Recommendation system — validation and learning boundary

- Current editorial score is 100 points: freshness (0–40), editorial brand fit (0–40), source-provenance completeness (0–10), and topic distinctiveness (0–10).
- Historical brand/region/topic performance, YouTube Analytics retention, and comparable cohorts are displayed as separate evidence; they do not currently alter ranking.
- The portal explicitly captures recommendation exposures through the snapshot endpoint. Only selected recommendations linked to production jobs can later contribute measured outcomes, so the resulting dataset is observational and selection-biased.
- Chronological holdout diagnostics require a minimum of five eligible recommendation runs for metric-level checks and at least ten distinct selected/measured outcomes for the outcome-level holdout. Per-cohort coverage is also checked.
- Automatic score adjustment remains disabled until real production data demonstrates stable improvement across holdouts. No ranking uplift or platform-algorithm advantage is claimed from mocked tests.

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
| BUILD-00001 | Durable queue and Worker Lease | CI lease/heartbeat regressions passed; production runtime verification pending |
| BUILD-00002 | Global trend ingestion | Provider/API/tests implemented; live and runtime validation pending |
| BUILD-00003 | Competitor/channel intelligence | Provider/API/tests implemented; API-key and runtime validation pending |
| BUILD-00004 | Profitability scoring and prioritization | Scenario calculator/API/tests implemented; runtime validation pending |
| BUILD-00005 | AI script, voice and video pipeline | Provider orchestration, lease-aware worker and API implemented; mocked tests committed; runtime/live-provider validation pending |
| BUILD-00006 | Ten-brand operations | Persistent 10-brand registry, activation controls and production market validation implemented; runtime validation pending |
| BUILD-00007 | Review and approval workflow | Decision store, authenticated APIs, audit snapshots and tests committed; runtime validation pending |
| BUILD-00008 | YouTube publishing and tracking | OAuth refresh-token adapter, approval-gated private resumable upload, upload ledger and Data API counter snapshots committed; live validation pending |
| BUILD-00009 | Revenue, cost and ROI analytics | Source-referenced financial ledger and separate revenue/cost reports committed; provider reconciliation pending |
| BUILD-00010 | AI performance analysis and strategy updates | Brand/region/video evidence, YouTube Analytics watch-time and retention, topic context and per-metric chronological holdout diagnostics; live-data and controlled-outcome validation pending |
| BUILD-00011 | Scheduling and recovery operations | Durable schedule outbox, atomic due-occurrence reservation and idempotent crash replay implemented; runtime validation pending |
| BUILD-00012 | Integrated validation and deployment | Docker Compose API/worker/scheduler/metrics-collector packaging and CI validation script committed; production deployment and runtime verification pending |

## BUILD-00198 — require stable cohorts for analytics holdouts

- Preserve analytics holdout diagnostics separately for each platform/brand/region/publication-age/duration/format cohort.
- Require the same comparable cohort to recur in at least five chronological exposure runs, with at least three selected and measured outcomes per run, before reporting a metric holdout.
- Do not aggregate unrelated cohorts across runs to manufacture apparent sample coverage.
- Add a regression where every run has three measured outcomes but the cohort rotates each time; the evaluator must report insufficient stable-cohort coverage.
- Automatic recommendation score adjustment remains disabled.

## BUILD-00199 — fail closed when review queue state is missing

- Require the durable queue table and a matching `short_video_production` queue row in `review_pending` before committing any human review decision.
- Reject approval, rejection, or revision decisions if the queue table or job row is missing; do not silently allow a production-ledger-only transition.
- Keep the production decision, queue transition, and audit event in one SQLite transaction.
- Update legacy-style unit fixtures to use matching queue-backed review records and add missing-table/missing-row rollback regressions.
- CI passed: run 43838159960; 564 backend tests, including missing-queue table/job rollback and queue-backed approval fixtures for YouTube, TikTok, and analytics.

## BUILD-00200 — fence TikTok publish attempts by current approval

- Recheck the latest human review decision, production-run status, and durable queue status inside the same `BEGIN IMMEDIATE` transaction that reserves a TikTok publish attempt.
- Require all three records to agree on an approved `short_video_production` job.
- Revalidate the approval artifact snapshot against current artifacts in that transaction, closing the race between publisher preflight and reviewer reopening.
- Add regressions for approval invalidation and queue-state mismatch immediately before attempt reservation.
- TikTok remains private-only (`SELF_ONLY`) and still requires explicit operator consent.

- CI passed: run 43838656483; 566 backend tests, including transactional current-approval and queue-state fencing regressions. Earlier runs exposed and corrected a test-call flag mismatch; final run passed.

## BUILD-00188 — integrity API input boundaries

- The read-only integrity endpoint enforces a page size of 1–200, offset of 0–1,000,000, and cursor length of at most 512 characters at the HTTP boundary.
- Cursor pagination cannot be combined with a non-zero offset; malformed cursors return HTTP 422 while storage configuration conflicts remain HTTP 409.
- The endpoint remains read-only and retains the existing production-read permission requirement.
- CI passed twice: runs 43832590556 and 43832598683; 549 backend tests in each run. The API boundary regression suite is included.

## BUILD-00189 — provider-attempt diagnostic redaction

- The provider-attempt read endpoint now returns operational metadata only; raw provider response JSON, signed artifact URLs, idempotency keys, provider request IDs, and raw transport errors are withheld.
- The endpoint reports whether a response/error exists and uses a fixed instruction to inspect protected server logs.
- Durable provider response data remains available to the server-side recovery/adoption flow; this change does not disable recovery.
- CI passed twice: runs 43832807638 and 43832847968; 550 backend tests in each run, including provider diagnostic redaction.

## BUILD-00190 — fence provider-attempt finalization by active worker lease

- Require the current, unexpired worker ID and fencing token before persisting either a provider response or an unknown transport outcome.
- Perform lease validation and attempt-state transition inside the same `BEGIN IMMEDIATE` transaction, preventing a stale worker from finalizing an attempt after its lease was replaced.
- Preserve the unresolved `request_started` record after a stale worker is rejected; reconcile the ambiguous external outcome rather than trusting a former lease holder.
- Add regression tests for stale response and stale transport-error finalization.
- CI passed: run 43833372844 (550 tests) and run 43833380845 (552 tests, including both stale-worker regressions).

## BUILD-00191 — redact provider diagnostics from review payloads

- Redact raw production-run errors returned by the authenticated production detail and review endpoints.
- Recursively remove provider credentials, idempotency/request identifiers, signed URL fields, response bodies, and raw transport errors from artifact metadata while retaining review-critical script, policy, and quality fields.
- Apply the same safe projection to pending and approved review payloads so legacy records are protected at read time without destroying server-side recovery data.
- Add regression coverage for nested provider secrets and raw errors in pending and approved review responses.
- CI passed: run 43833989205 (553 tests) and run 43834132229 (554 tests, including production-detail and generic token redaction regressions).

## BUILD-00192 — redact platform publishing diagnostics

- Apply the shared response-time sanitizer to YouTube upload and TikTok publication detail APIs.
- Sanitize platform error fields and immutable event payloads in the approved-review list while preserving statuses, reconciliation flags, video IDs, and operator-visible audit context.
- Keep raw diagnostic details in protected server-side storage; never return bearer-like provider error text through routine publishing reads.
- Add API regression tests for both platform detail routes and the combined approved-review payload.
- CI passed: run 43834493668 (554 tests) and run 43834500529 (556 tests, including YouTube/TikTok publication redaction regressions).

## BUILD-00193 — redact queue and worker diagnostic responses

- Sanitize queue job error messages and worker-pause event details returned by queue read APIs.
- Sanitize worker-control pause reasons and system-generated pause/resume audit messages while preserving operator-authored maintenance notes.
- Apply safe response projections to production reconciliation reads and retry reconciliation results.
- Preserve raw diagnostic context in durable server-side records for protected investigation.
- Add regression tests for job, event, and worker-control response redaction.
- CI passed: run 43834848565 (556 tests) and run 43834852097 (558 tests, including queue/job/event and worker-control redaction regressions).

## BUILD-00194 — sanitize provider failure responses

- Stop embedding raw HTTP error response bodies in provider exceptions; retain only the HTTP status code and retryability.
- Return a fixed, stage-aware API error message from production execution instead of exposing provider exception text to the caller.
- Preserve detailed failure context in protected server-side records for operator investigation.
- Add regression tests proving provider response bodies and bearer-like values are absent from exceptions and API responses.
- CI passed: run 43835160754 and run 43835170439; 559 backend tests in each run, including provider HTTP body and API response redaction.

## BUILD-00195 — verify lease renewal during active provider execution

- Add an integration-style worker regression that keeps provider execution active until a real heartbeat callback is observed.
- Verify the active pipeline receives the exact lost-lease stop event and that a successful heartbeat permits the normal review-pending handoff.
- Confirm the worker always stops and joins its heartbeat thread after execution.
- This validates the local supervised worker path; it does not claim external API clients automatically renew leases.
- CI passed: run 43835489554; 560 backend tests, including the active-provider heartbeat regression.

## BUILD-00196 — keep deterministic policy blocks job-scoped

- Handle `PolicyBlocked` before the generic provider-error branch in the production execution API.
- Terminalize only the blocked job with a dedicated `policy_blocked` error code and HTTP 422 response.
- Do not pause the shared production queue for a deterministic content-policy preflight block; unrelated eligible jobs remain runnable.
- Add an API regression proving the job is failed and the global worker pause is not invoked.
- CI passed: run 43835765458 (560 tests) and run 43835771230 (561 tests, including the API policy-block isolation regression).

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

- Added `backend/worker.py`: long-running worker claims only short-video jobs, renews its lease during provider work, and finalizes successful jobs at the human review gate. Queue claim now supports job-type filtering. Artifact writes are retry-safe by stage.

## Validation — current truth

- Latest verified candidate CI run: [43814901569](https://github.com/justinhblee-prog/shorts/actions/runs/43814901569), which passed **516 backend tests** and the complete `scripts/validate.sh` command for BUILD-00171.
- CI executed Python 3.11 tests on a GitHub-hosted runner. Provider/API tests use controlled test doubles where credentials or external services are required; this verifies application logic, not live provider success.
- The validation script also checks Python compilation, frontend JavaScript syntax/DOM IDs and Docker Compose YAML parsing.
- Recent verified milestones: BUILD-00164 scheduler outbox retry backoff — 500 tests; BUILD-00167 inactive-schedule dead-letter protection — 506 tests; BUILD-00168 scheduler outbox dashboard recovery — 507 tests; BUILD-00169 database readiness probe — 510 tests; BUILD-00170 strict worker runtime configuration — 514 tests; BUILD-00171 worker heartbeat observability — 516 tests.
- Not yet verified in a deployed environment: live AI provider generation, actual media rendering/staging, YouTube/TikTok OAuth and account permissions, real uploads, analytics coverage, revenue reconciliation, production worker/scheduler recovery, PostgreSQL migration, backups and restore.
- No real earnings, monetization eligibility, platform-policy approval or complete unattended business cycle is claimed.
- Production public publishing remains gated by explicit human approval.

## BUILD-00005 — AI script, voice and video production pipeline

- Added `backend/production_pipeline.py` with provider-neutral JSON HTTP adapters, persistent production run/artifact records, strict brief validation, and ordered script → voice → render orchestration.
- Added production job submission, inspection and lease-token-protected execution endpoints in `backend/app.py`.
- Requires runtime configuration for script, voice and render provider URLs; optional bearer tokens are supported. Vendor-specific endpoints must conform to the documented JSON contracts or be wrapped by a provider adapter.
- Missing provider configuration, missing script text, missing audio URL or missing video URL fails closed. No fake generation outputs are returned.
- A successful render ends at `review_pending`; no public publishing action is included.
- Mock-provider contract tests are committed in `backend/tests/test_production_pipeline.py`.
- **CI validated:** the current repository suite runs successfully in GitHub Actions. **Not validated:** real provider API compatibility, real audio/video generation, media playback, render quality, or end-to-end production.


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
- GitHub Actions PR run [43784004930](https://github.com/justinhblee-prog/shorts/actions/runs/43784004930) passed **326 backend tests**; `scripts/validate.sh` completed successfully.


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
- GitHub Actions PR run [43798469723](https://github.com/justinhblee-prog/shorts/actions/runs/43798469723) passed **464 backend tests** and the complete `scripts/validate.sh` command.


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
- Add regression tests for the policy engine, API model and review-store evidence update. GitHub Actions run [43780970297](https://github.com/justinhblee-prog/shorts/actions/runs/43780970297) passed **255 backend tests** and `scripts/validate.sh`. PR #85 was squash-merged into `main` as `8c5b67313072a4b3f1f2599c9c6e982f11886ab4`.


### BUILD-00027 — TikTok private-only publishing backend (2026-11-16)

- Add encrypted TikTok Login Kit OAuth with one-time state, token encryption/rotation, refresh lease and redacted callback access logs.
- Add TikTok Direct Post private-only publisher. Require latest human approval, exact artifact snapshot, current policy version/date, TikTok AIGC disclosure, explicit operator consent, explicit branded-content toggles, creator-info lookup and available SELF_ONLY privacy level.
- Verify staged media fingerprint and upload only a private immutable snapshot; enforce media format/duration constraints and block ambiguous retries pending reconciliation.
- Add TikTok owned-video metrics collection using a separate lease and isolate provider failures from YouTube collection.
- Add protected API endpoints and regression tests. GitHub Actions run [43781739033](https://github.com/justinhblee-prog/shorts/actions/runs/43781739033) passed **317 backend tests** and `scripts/validate.sh`. PR #87 was squash-merged into `main` as `43b8c0048e117af3864908e23f50dcf2b3443c9f`. Frontend controls and live TikTok developer-app/account audit remain separate tasks.


### BUILD-00028 — TikTok operator controls in the review workspace (2026-11-16)

- Extend the approved queue with TikTok publication state so a video remains visible until both YouTube and TikTok are complete.
- Add TikTok OAuth connection/status, creator-info and private publishing controls to the review workspace.
- Require explicit consent, SELF_ONLY privacy, and separate brand-content/own-brand declarations; prevent selecting both commercial categories simultaneously.
- Add publication status refresh, operator reconciliation, and owned-video metrics display.
- The UI stages media before posting and stops for re-review if staging changes the approved fingerprint. GitHub Actions run [43782071923](https://github.com/justinhblee-prog/shorts/actions/runs/43782071923) passed **317 backend tests** and `scripts/validate.sh`. PR #89 was squash-merged into `main` as `2ea68c4314f11c23fdcaafd31f648adc5d4c1fef`. Real OAuth/developer-app/account testing remains external.


### BUILD-00029 — platform-specific performance and recommendation evaluation (2026-11-16)

- Add TikTok performance analysis from owned-video Display API snapshots: view velocity and like/comment/share deltas, elapsed-time normalization, and brand/region/topic/duration/format/age cohorts.
- Add platform column and additive migration to recommendation exposure records; deduplicate, link selected production jobs and evaluate outcomes only within the same platform.
- Add platform selector to trend recommendation workspace and platform-specific holdout evaluation panel.
- Add platform field to trend production drafts and policy platform selection so TikTok recommendations create TikTok-scoped production jobs.
- Keep recommendation score adjustment disabled; TikTok API does not expose audience retention/watch-time/estimated revenue in this collector. GitHub Actions run [43782980545](https://github.com/justinhblee-prog/shorts/actions/runs/43782980545) passed **320 backend tests** and `scripts/validate.sh`. PR #91 was squash-merged into `main` as `883870472bb1784ea093b65698221890d6db4b06`.


### BUILD-00030 — platform-aware manual and scheduled production (2026-11-16)

- Add platform selection to the normal production request and recurring schedule API/UI.
- Persist selected platform as the production brief's `platforms` list through the schedule outbox and queue dispatch, so scheduled TikTok jobs receive TikTok policy preflight and TikTok publishing eligibility.
- Display the platform on each scheduled job and add regression tests for schedule payload persistence and API model validation.
- GitHub Actions run [43783409343](https://github.com/justinhblee-prog/shorts/actions/runs/43783409343) passed **322 backend tests** and `scripts/validate.sh`. PR #93 was squash-merged into `main` as `cd5f8c4f1c1e780732457450ae2f215d4ef13950`.


### BUILD-00031 — accurate provider and platform integration preflight (2026-11-16)

- Treat script, voice and renderer bearer tokens as optional settings; provider URLs remain required. Optional omissions no longer make AI generation appear unconfigured.
- Report TikTok Login Kit OAuth configuration separately from the optional static access-token fallback.
- Expose platform-specific configuration readiness for YouTube Shorts and TikTok while keeping metrics readiness and live connectivity separate.
- Preserve the existing `end_to_end_configured` field as the YouTube-oriented compatibility summary.
- Add regression tests for optional provider tokens, TikTok OAuth readiness, static-token fallback, secret redaction and fail-closed empty configuration.
- Configuration checks do not verify live provider compatibility, OAuth scopes, creator permissions, platform connectivity or publishing.
- GitHub Actions PR run [43784004930](https://github.com/justinhblee-prog/shorts/actions/runs/43784004930) passed **326 backend tests**; `scripts/validate.sh` completed successfully. The test run covered the code head before documentation-only validation-record commits and the PR was squash-merged as `7ce6e7fd5a52d7510369c853ec0126bcefcd9527`.


### BUILD-00032 — YouTube Analytics watch-time and audience retention (2026-11-16)

- Add `backend/youtube_analytics.py` with channel-authorized YouTube Analytics API v2 reports for views, estimated minutes watched, average view duration and average view percentage.
- Collect per-video audience-retention curves from elapsed-video-time ratio, audience-watch ratio and relative-retention performance. Retention query failures are isolated from core watch-time reports.
- Persist reports in an additive SQLite table with a separate collector lease; run daily from the existing metrics-collector service and support protected manual refresh/read endpoints.
- Add per-video and brand-level median Analytics evidence to performance insights and dashboard; missing/eligibility-limited metrics remain null and are not inferred.
- Recommendation ranking remains unchanged; analytics are evidence for later controlled holdout evaluation, not an automatic score input.
- GitHub Actions PR run [43785987107](https://github.com/justinhblee-prog/shorts/actions/runs/43785987107) passed **336 backend tests** and `scripts/validate.sh`. The run validated the implementation code; the later documentation-only commit corrected the API endpoint list formatting.


### BUILD-00033 — retention-aware recommendation evidence and holdout evaluation (2026-11-16)

- Extend topic-matched historical performance context to include Analytics-only videos, average view percentage, average view duration and source-reported audience-watch ratios at the 25%, 50% and 75% video-time points.
- Extend recommendation evaluation to accept Analytics outcomes even when two public counter snapshots are not yet available; retain the existing snapshot-derived views/hour evaluation unchanged.
- Calculate separate chronological, within-exposure comparable-cohort holdouts for average view percentage, average view duration and audience-watch ratios at 25/50/75%.
- Require at least five eligible recommendation exposure runs and three selected/measured candidates per comparable cohort for each metric-specific holdout.
- Display topic-matched watch-quality evidence and metric-specific holdout coverage in the dashboard.
- No recommendation score adjustments are enabled; these are observational diagnostics over selected production only and do not establish causal lift.
- GitHub Actions PR run [43786466302](https://github.com/justinhblee-prog/shorts/actions/runs/43786466302) passed **338 backend tests** and `scripts/validate.sh`.


### BUILD-00034 — Shorts engaged-view quality signal (2026-11-16)

- Extend YouTube Analytics collection with the core `engagedViews` metric alongside `views`, watch time and retention.
- Add an additive SQLite migration for `engaged_views` and derived `engaged_view_share = engagedViews / views`; do not label the derived ratio as a platform-provided rate.
- Surface engaged-view share in per-video and brand performance, topic-matched historical context and recommendation holdout diagnostics.
- Keep the signal separate from public Data API counters and existing views/hour; do not change recommendation scores.
- GitHub Actions run [43787457716](https://github.com/justinhblee-prog/shorts/actions/runs/43787457716) passed **339 backend tests** and `scripts/validate.sh`.


### BUILD-00034 validation record

- GitHub Actions PR run [43787047727](https://github.com/justinhblee-prog/shorts/actions/runs/43787047727) passed **339 backend tests** and `scripts/validate.sh`.
- Regression tests cover legacy SQLite migration, engagedViews parsing, derived share, performance aggregation, topic history and recommendation holdout evidence.
- No recommendation score adjustment or live YouTube account verification is claimed.


### BUILD-00035 — audience-retention curve visualization (2026-11-16)

- Sort stored audience-retention points by elapsed video-time ratio before exposing them to the dashboard.
- Display a per-video sparkline plus the 25%, 50% and 75% audience-watch-ratio checkpoints.
- Label checkpoint values as ratios (x), not percentages, because the absolute audience-watch ratio can exceed 1 when viewers replay a segment.
- Preserve unavailable/empty retention as an explicit no-data state; no curve is synthesized.

### BUILD-00036 — encrypted YouTube OAuth account connection (2026-11-16)

- Add server-side Google OAuth authorization-code flow with random one-time state, secure HttpOnly callback cookie and access-log query redaction.
- Request YouTube upload, YouTube read-only and YouTube Analytics read-only scopes; require upload and YouTube read-only scopes before storing a connection.
- Encrypt the refresh token at rest with Fernet using YOUTUBE_TOKEN_ENCRYPTION_KEY; do not persist the access token or expose token values in status.
- Use the encrypted token store for YouTube uploads and Analytics, with the legacy YOUTUBE_REFRESH_TOKEN environment variable as a compatibility fallback.
- Add protected connect/status/disconnect endpoints and dashboard connection controls.
- GitHub Actions PR run [43794744350](https://github.com/justinhblee-prog/shorts/actions/runs/43794744350) passed **436 backend tests** and the complete `scripts/validate.sh` command. Live Google consent, account selection, refresh and real upload remain deployment checks.


### BUILD-00036 validation record

- GitHub Actions PR run [43788265493](https://github.com/justinhblee-prog/shorts/actions/runs/43788265493) passed **352 backend tests** and `scripts/validate.sh`.
- Test coverage includes one-time OAuth state, required-scope enforcement, encrypted token persistence, disconnect, static-token fallback, preflight and protected/public callback route boundaries.
- Live Google consent, refresh-token usability, actual channel API access and a real upload remain deployment checks.


### BUILD-00037 — live YouTube account and Analytics verification (2026-11-16)

- Add an explicit protected verification action that refreshes the stored OAuth token and calls YouTube Data API v3 `channels.list(mine=true)`.
- Independently call YouTube Analytics API v2 for a channel-level views report; Data API success remains visible if Analytics permission is missing.
- Persist channel ID/title, last verification time and separate Data API/Analytics API outcomes; status distinguishes stored OAuth approval from live connectivity.
- Require the encrypted OAuth connection for persistent verification; legacy environment tokens remain usable for compatibility but do not produce a persisted verified-account status.
- GitHub Actions PR run [43795106625](https://github.com/justinhblee-prog/shorts/actions/runs/43795106625) passed **438 backend tests** and the complete `scripts/validate.sh` command. Live verification only occurs when the operator runs the action with a real account.


### BUILD-00037 validation record

- GitHub Actions PR run [43788723765](https://github.com/justinhblee-prog/shorts/actions/runs/43788723765) passed **356 backend tests** and `scripts/validate.sh`.
- Tests cover both API checks, partial Analytics permission failure, verification persistence and migration from the prior OAuth token schema.
- Live Google channel verification was not executed; it is an operator-triggered deployment step.


### BUILD-00038 — automated SQLite and media backup/restore (2026-11-16)

- Add a SQLite online-backup API snapshot plus media-file archive with SHA-256 manifest and integrity checks.
- Add a Compose backup service that runs immediately and repeats daily, retaining 14 days by default in a separate named volume.
- Add guarded restore requiring explicit `--confirm-restore`, validates archive paths/checksums/SQLite integrity before changing live data, and creates a pre-restore backup.
- Restore stages new DB/media beside their destinations and rolls back filesystem replacements on failure.
- Harden restore with archive-entry, manifest, database and media size caps; validate manifest structure, checksums, path uniqueness and exact file inventory before extraction.
- Reject traversal paths, backslashes, NULs, links, special files, duplicate archive paths and unexpected control-file paths. Preserve empty media directories.
- Backups contain the database and media only; environment secrets/encryption keys are not included. The backup volume is not off-site and must be copied to independent storage.
- Restore must be run offline after stopping API, worker, scheduler, metrics collector and backup service.
- Final hardening CI [43789858034](https://github.com/justinhblee-prog/shorts/actions/runs/43789858034) passed **365 backend tests** and `scripts/validate.sh`.


### BUILD-00038 validation record

- GitHub Actions PR run [43789308031](https://github.com/justinhblee-prog/shorts/actions/runs/43789308031) passed **362 backend tests** for the initial backup implementation.
- After restore hardening, GitHub Actions PR run [43789858034](https://github.com/justinhblee-prog/shorts/actions/runs/43789858034) passed **365 backend tests** and `scripts/validate.sh`.
- Tests verify SQLite online backup, media manifest/checksums, restore confirmation, pre-restore backup, rollback-safe replacement and symlink/path rejection.
- Compose YAML validation passed. The scheduled backup service has not been deployed or observed in a running environment.


### BUILD-00039 — per-operator RBAC and persistent API rate limits (2026-11-16)

- Add per-operator token authentication with a fixed legacy shared-token identity for controlled migration; configured individual credentials replace the legacy fallback.
- Add explicit role permissions for admin, producer, reviewer, publisher, analyst, operator, finance and worker roles; protected API routes now declare permission guards.
- Ignore caller-supplied reviewer IDs for policy evidence and review decisions; persist the authenticated token identity instead.
- Add atomic SQLite fixed-window rate limits by client identity and request class, with response headers and 429 retry information.
- Trust X-Forwarded-For only when the immediate peer belongs to an explicitly configured trusted proxy CIDR; default is no trusted proxies.
- GitHub Actions run [43790865052](https://github.com/justinhblee-prog/shorts/actions/runs/43790865052) passed **400 backend tests** and `scripts/validate.sh`.



## BUILD-00130 — authenticated encryption for complete SQLite and media backups

- Added streaming AES-256-GCM encryption for complete `.tar.gz` backup archives, not only the SQLite file.
- Encryption keys are URL-safe base64 values decoding to exactly 32 bytes and are read from `NEXUS_BACKUP_ENCRYPTION_KEY`; they are never accepted as command-line arguments or written into archive metadata.
- Encrypted archives use the `.tar.gz.enc` suffix and a versioned header. Restore authenticates the complete ciphertext before extracting any files; wrong keys, tampering and truncation fail before live data is touched.
- `NEXUS_BACKUP_ENCRYPTION_REQUIRED=true` refuses plaintext backup creation and restore. With the default false setting, legacy plaintext archives remain readable.
- Pre-restore backups inherit the active encryption key; retention handles encrypted and plaintext archives together. Archive files are restricted to owner-only permissions on POSIX systems.
- Preflight reports invalid/missing keys and whether encryption is mandatory. GitHub Actions run [43791757173](https://github.com/justinhblee-prog/shorts/actions/runs/43791757173) passed **408 backend tests** and `scripts/validate.sh`.
- Losing the key makes encrypted backups unrecoverable. Keep it in a secret manager/off-host secure location separate from backup storage; no key is committed.


## BUILD-00131 — optional ClamAV malware gate for staged media

- Added a local ClamAV scanner that runs without a shell and requires exit code 0 for a clean result; infected files, missing binaries, unavailable signatures, scanner errors and timeouts fail closed.
- The scanner runs after bounded HTTPS download, allowlist/DNS checks, Content-Length validation and MP4 signature checks, but before the temporary file is atomically published as staged media. It explicitly sets ClamAV file/scan size limits and `--alert-exceeds-max=yes`; ClamAV defaults can otherwise skip over-limit files and assume them clean.
- Scanning is opt-in via `NEXUS_MEDIA_SCAN_ENABLED=true`; disabled mode does not construct the scanner and reports `malware_scan=disabled`.
- Added a persistent `clamav_db` volume and a `media-scan` Compose profile running `freshclam`; the API mounts signatures read-only. Preflight checks executable, signature files and timeout before reporting the feature ready.
- Docker image now includes `clamav` and `clamav-freshclam`; image size and signature storage increase. CI uses injected scanner stubs and does not download or validate live signatures.
- GitHub Actions run [43792634688](https://github.com/justinhblee-prog/shorts/actions/runs/43792634688) passed **427 backend tests** and `scripts/validate.sh`. No production ClamAV scan or signature refresh is claimed.


## BUILD-00132 — evidence-gated YouTube retention diagnostics and analytics cohorts (2026-11-16)

- Derive descriptive retention-curve diagnostics from stored YouTube Analytics API audience-watch-ratio points: early retention, end retention and the largest adjacent observed drop-off segment.
- Compare average view percentage, average view duration and engaged-view share only within matched brand/region/publication-age/duration/format/exact-topic cohorts.
- Require at least three videos in a cohort before emitting a comparative observation; sparse cohorts remain explicitly limited.
- Emit video-level descriptive observations for above/below cohort median retention, with controlled-test suggestions. Never modify recommendation ranking scores.
- Ignore malformed, non-finite and out-of-range retention points; do not infer causal reasons from curve shape.
- GitHub Actions PR run [43794456586](https://github.com/justinhblee-prog/shorts/actions/runs/43794456586) passed **431 backend tests** and the complete `scripts/validate.sh` command.


## BUILD-00133 — scheduled YouTube Analytics OAuth and lease renewal (2026-11-16)

- Wire the periodic Analytics collector to the same encrypted `YouTubeOAuthManager` token store used by the API/manual refresh path; do not require the legacy plaintext `YOUTUBE_REFRESH_TOKEN` environment variable after OAuth setup.
- Renew the collector's SQLite lease during long batches; renewal is conditional on the same owner and an unexpired lease, so an expired owner cannot resurrect its lease.
- Make the lease duration configurable with `YOUTUBE_ANALYTICS_LEASE_SECONDS` (default 900 seconds); heartbeat interval is one-third of the lease.
- Preserve provider failure isolation and ensure the lease is released in all exit paths.
- GitHub Actions PR run [43794744350](https://github.com/justinhblee-prog/shorts/actions/runs/43794744350) passed **436 backend tests** and the complete validation script.


## BUILD-00134 — YouTube Analytics collection observability (2026-11-16)

- Persist scheduled collection status and batch totals for `running`, `succeeded`, `partial` and `failed` outcomes.
- Expose the last attempt, last successful cycle, sanitized error summary, last batch counts and latest report timestamp.
- Calculate coverage across uploaded videos: with snapshot, without snapshot and stale/missing according to the configured Analytics minimum age.
- Add authenticated `GET /api/youtube/analytics/collection-status` and surface the collector state/coverage in the performance dashboard.
- Preserve previous completed batch totals and last error while a new batch is running; a completed successful batch clears the prior error.
- GitHub Actions PR run [43795106625](https://github.com/justinhblee-prog/shorts/actions/runs/43795106625) passed **438 backend tests** and the complete validation script.


## BUILD-00135 — validate YouTube and TikTok metrics response batches (2026-11-16)

- Validate YouTube Analytics column names, duplicate headers, row shape/count, requested metric set and finite nonnegative numeric values before using report data.
- Bound Analytics response columns and rows; validate retention point ranges and ignore malformed retention reports without discarding otherwise valid watch-time metrics.
- Validate the complete TikTok response batch, reject unrequested/duplicate IDs and SQLite integer overflow, then persist all accepted rows in one transaction.
- Add regression tests proving a malformed later TikTok row cannot leave an earlier partial snapshot, and malformed YouTube report values are rejected.
- GitHub Actions PR run [43795614217](https://github.com/justinhblee-prog/shorts/actions/runs/43795614217) passed **446 backend tests** and the complete `scripts/validate.sh` command.


## BUILD-00136 — safe external media URL rendering (2026-11-16)

- Add a single URL validator for external renderer video links and narration audio previews.
- Permit only absolute HTTPS URLs and reject malformed URLs, non-HTTPS schemes and embedded username/password credentials.
- Hide unsafe media controls instead of placing untrusted URLs in href/src attributes.
- Opened media links use both `noopener` and `noreferrer`.
- Add frontend regression tests for review video, approved video and audio preview paths.
- GitHub Actions PR run [43795822579](https://github.com/justinhblee-prog/shorts/actions/runs/43795822579) passed **447 backend tests** and the complete `scripts/validate.sh` command.


## BUILD-00137 — lifecycle-safe production cancellation and worker shutdown (2026-11-16)

- Restrict production cancellation to pre-review states and reject cancellation after review handoff or approval/upload.
- Update queue and production-run state in one SQLite transaction so a cancelled job cannot be reconciled back into review.
- Treat cancellation during a running provider request as externally ambiguous, revoke the worker lease, and pause production until manual reconciliation.
- Persist graceful worker shutdown as `offline`; stale-heartbeat detection remains the fallback for hard crashes.
- Add tests for queued/running/review-pending cancellation, production-state consistency and offline worker registration.
- GitHub Actions PR run [43796187131](https://github.com/justinhblee-prog/shorts/actions/runs/43796187131) passed **451 backend tests** and the complete `scripts/validate.sh` command.


## BUILD-00138 — renewable token-fenced metrics collector leases (2026-11-16)

- Add a shared heartbeat helper for YouTube Data API counters, YouTube Analytics and TikTok Display API collection.
- Renew leases during long batches and verify ownership before/after provider work.
- Add unique lease tokens to YouTube Data API and YouTube Analytics leases; preserve TikTok's token lease. Reject stale snapshot and collection-state writes inside the same SQLite transaction.
- Pass lease owner/token through collector batches so a replaced or expired worker cannot persist late results.
- Make YouTube Data API/TikTok lease duration configurable with `NEXUS_METRICS_LEASE_SECONDS` (default 300 seconds); YouTube Analytics remains separately configurable (default 900 seconds).
- Add tests for lease renewal, expiry, replacement-token fencing, runner failure cleanup and heartbeat loss.
- GitHub Actions PR run [43797131269](https://github.com/justinhblee-prog/shorts/actions/runs/43797131269) passed **462 backend tests** and the complete `scripts/validate.sh` command.


## BUILD-00139 — exact recommendation exposure attribution (2026-11-16)

- Carry the captured `evaluation_run_id` from the recommendation snapshot into the selected production draft request.
- Link a production job only to the exact recommendation run, trend and brand that the operator selected; never infer attribution from the newest matching exposure.
- Ordinary trend-to-production drafts do not create recommendation-evaluation outcomes unless they carry an explicit captured recommendation run ID.
- Return an explicit attribution result to the dashboard when a recommendation selection is linked or cannot be linked.
- Add regression tests for two refreshes of the same recommendation, exact older-run selection, missing/stale run IDs and cross-platform isolation.
- GitHub Actions PR run [43798545897](https://github.com/justinhblee-prog/shorts/actions/runs/43798545897) passed **464 backend tests** and the complete `scripts/validate.sh` command. The code and validation-record documentation are merged in PR #131.


## BUILD-00140 — capture all selectable brand candidates in recommendation exposures (2026-11-16)

- Persist every brand option displayed by the recommendation dashboard, rather than only the top-ranked `best_brand`.
- Store candidate-specific brand fit and comparable-cohort context alongside the trend-level recommendation rank and score.
- Keep legacy recommendation payloads compatible by falling back to `best_brand` when `brand_candidates` is absent or empty.
- Include all recorded brand options in the exposure signature so changing the selectable alternatives creates a distinct exposure instead of being incorrectly deduplicated.
- Add regression tests for selecting a non-default brand and for exposure signature changes when alternate brands change.
- GitHub Actions PR run [43798824433](https://github.com/justinhblee-prog/shorts/actions/runs/43798824433) passed **466 backend tests** and the complete `scripts/validate.sh` command.


## BUILD-00141 — refresh repository validation summary

- Refresh the top-level validation checkpoint to the latest verified BUILD-00140 CI run.
- Replace the stale 408-test summary with the current 466-test result and link to the exact GitHub Actions run.
- Keep all live-provider, account, deployment and revenue limitations explicit.


## BUILD-00145 — strict recommendation evidence metric validation

- Reject booleans, non-finite values and invalid numeric inputs before exposing topic-matched historical performance context.
- Require engaged-view share and audience-retention ratios to remain within 0–1; preserve valid average view percentages above 100%.
- Reject boolean competitor view counts and malformed interaction-rate metrics.
- Add regression coverage for malformed topic evidence and competitor counters.
- GitHub Actions run [43800466202](https://github.com/justinhblee-prog/shorts/actions/runs/43800466202) passed the complete `scripts/validate.sh` workflow on the final code/test commit.


## BUILD-00146 — comparable cohort evidence validation

- Reject malformed cohort records and boolean/negative/coerced sample counts.
- Normalize cohort medians to finite nonnegative metrics and derive evidence status from validated counts.
- Preserve display-only cohort context; ranking adjustment remains zero.
- Add regression coverage for invalid and valid cohort aggregates.
- GitHub Actions run [43802473568](https://github.com/justinhblee-prog/shorts/actions/runs/43802473568) passed the complete `scripts/validate.sh` workflow on the regression-test commit.


## BUILD-00147 — recommendation outcome ingress validation

- Reject boolean, non-finite, negative and overflowing outcome metrics at evaluation ingress.
- Enforce normalized ratio bounds for engaged-view share and audience-retention coordinates.
- Preserve valid average view percentages above 100%.
- Add regression tests; ranking adjustment remains disabled.
- GitHub Actions run [43803213470](https://github.com/justinhblee-prog/shorts/actions/runs/43803213470) passed the complete `scripts/validate.sh` workflow on the corrected code/test commit.


## BUILD-00148 — recommendation exposure ingress validation

- Harden exposure recording against malformed recommendation rows and nested trend/brand objects.
- Reject boolean, non-finite, negative and overflowing recommendation scores before SQLite persistence.
- Bound and validate brand identifiers/names; recursively normalize score/cohort metadata to JSON-safe values.
- Add regression tests for malformed payloads and invalid ranking evidence.
- GitHub Actions run [43803752778](https://github.com/justinhblee-prog/shorts/actions/runs/43803752778) passed the complete `scripts/validate.sh` workflow on the code/test commit; documentation-only commits followed.
- Ranking score adjustment remains disabled; no live provider validation is claimed.


## BUILD-00149 — recommendation cohort dimension validation

- Normalize job IDs, platform labels and cohort dimensions to bounded, trimmed strings.
- Reject malformed container values and oversized labels before constructing evaluation cohort keys.
- Prevent unhashable provider metadata from crashing recommendation evaluation.
- Add regression coverage for malformed, oversized and whitespace-padded dimensions.
- GitHub Actions run [43804517687](https://github.com/justinhblee-prog/shorts/actions/runs/43804517687) passed the complete `scripts/validate.sh` workflow on the code/test commit; documentation-only commits followed.
- Ranking score adjustment remains disabled; live provider validation is not claimed.


## BUILD-00150 — recommendation timestamp ingress validation

- Validate exposure and production-selection timestamps as ISO-8601 before persistence; naive timestamps are explicitly normalized to UTC.
- Reject malformed region labels and invalid production trend/brand/job identities at the SQLite ingress boundary.
- Require platform values to be supported strings.
- Add regression coverage for malformed timestamp, region and identity payloads.
- GitHub Actions run [43805417830](https://github.com/justinhblee-prog/shorts/actions/runs/43805417830) passed `scripts/validate.sh` after the timestamp-defaulting regression fix.
- Ranking score adjustment remains disabled; no live provider validation is claimed.


## BUILD-00151 — bounded recommendation trend identifiers

- Enforce the same 160-character trend identifier limit when capturing recommendation exposures that is already required when linking a production selection.
- Drop overlong identifiers before persistence so candidates cannot be stored in a state that the production-link API can never select.
- Add a regression test proving overlong IDs are excluded while valid candidates remain selectable.
- Ranking score adjustment remains disabled; no live provider validation is claimed.


## BUILD-00152 — duplicate performance outcome isolation

- Detect repeated performance rows for the same normalized production job within one evaluation payload.
- Exclude duplicated job IDs instead of allowing last-write-wins behavior to make metrics depend on input ordering.
- Add a regression test covering conflicting duplicate measurements alongside a valid unique outcome.
- Evaluation remains observational and score adjustments remain disabled.


## BUILD-00153 — malformed audience-retention payload isolation

- Treat a non-list `audience_retention_curve` value (including null, scalar and string payloads) as unavailable retention evidence rather than allowing iteration to raise and abort the entire recommendation evaluation.
- Preserve independently valid metrics such as views/hour for the affected production outcome; retention checkpoints remain null when no valid curve is supplied.
- Add regression coverage for malformed curve containers and verify the evaluation batch remains available.
- Recommendation ranking remains unchanged; no live provider/account validation is claimed.


## BUILD-00154 — YouTube Analytics storage-boundary numeric validation

- Reject Python booleans as numeric Analytics values instead of coercing `True`/`False` to 1/0.
- Enforce 0–1 bounds for elapsed-video-time and audience-watch retention ratios at the persistence boundary; keep valid relative-retention negative values.
- Preserve valid average view percentages above 100% and other valid metrics when unrelated fields are malformed.
- Add direct-store regression coverage for booleans, negative/out-of-range ratios and valid boundary values.


## BUILD-00155 — complete TikTok published-video metrics coverage

- Add a lightweight publication-store query for all completed TikTok publications with video IDs; avoid the UI's intentionally bounded 200-record history API for analytics collection and coverage.
- Use the complete eligible publication set when scheduling due metrics and calculating coverage, while keeping the dashboard's recent-metrics display bounded to its requested limit.
- Add regression coverage with more than 200 completed publications to verify full coverage and that collection can reach records beyond the recent-history window.
- TikTok Display API requests remain capped at 20 videos per collection run; this change does not claim live TikTok account validation.
- GitHub Actions run [43808106089](https://github.com/justinhblee-prog/shorts/actions/runs/43808106089) passed the complete `scripts/validate.sh` workflow on the final code/test commit.


## BUILD-00156 — prevent TikTok missing-video retry starvation

- Persist retry backoff for published video IDs omitted from an otherwise valid TikTok Display API response.
- Exclude temporarily deferred IDs from subsequent due batches so a repeatedly missing newest batch cannot starve older published videos.
- Apply bounded exponential retry delay (six-hour base, capped at seven days); clear the retry state as soon as a valid snapshot is saved.
- Add regression tests proving the next batch advances to older videos and successful collection clears the defer state.
- This handles provider omissions only; no live TikTok account validation or inference about why a video is absent is claimed.
- GitHub Actions run [43808258956](https://github.com/justinhblee-prog/shorts/actions/runs/43808258956) passed the complete `scripts/validate.sh` workflow on the final code/test commit.


## BUILD-00157 — atomic TikTok metrics batch persistence

- Persist successfully returned metric snapshots and retry backoff for omitted video IDs within the same SQLite transaction.
- Prevent process interruption or a retry-state write failure from committing only half of a provider batch, which could otherwise reintroduce starvation or lose collected snapshots.
- Validate missing IDs and reject overlap between collected and missing IDs before opening the write transaction.
- Add regression tests that inject a retry-table write failure and verify that no snapshot is partially committed, plus a successful mixed-result collector test.
- Provider/account behavior remains unverified against a live TikTok account.
- GitHub Actions run [43808905182](https://github.com/justinhblee-prog/shorts/actions/runs/43808905182) passed the complete `scripts/validate.sh` workflow on the final code/test commit.


## BUILD-00158 — bound TikTok metrics collector lease duration

- Validate collector lease durations as non-boolean integers between 1 and 3600 seconds before acquiring or renewing a lease.
- Preserve the existing 30-second minimum while preventing floats, strings, booleans, non-positive values, and arbitrarily long leases from being silently coerced.
- Add regression coverage for invalid inputs, minimum-duration behavior, and renew-time validation.
- GitHub Actions run [43809118955](https://github.com/justinhblee-prog/shorts/actions/runs/43809118955) passed the complete `scripts/validate.sh` workflow on the final code/test commit.


## BUILD-00159 — bound worker queue and scheduler lease TTL

- Apply strict lease-duration validation to the durable worker queue and scheduler leader lease.
- Accept only non-boolean integers from 1 to 3600 seconds; preserve the existing minimum TTLs (10 seconds for worker jobs, 15 seconds for scheduler leadership).
- Reject floats, strings, booleans, non-positive values, and unbounded TTLs before worker or scheduler state is initialized or renewed.
- Add regression coverage for constructor validation and scheduler acquire/renew validation.
- GitHub Actions run [43809336911](https://github.com/justinhblee-prog/shorts/actions/runs/43809336911) passed the complete `scripts/validate.sh` workflow on the final code/test commit.


## BUILD-00161 — strict production schedule interval validation

- Reject boolean, float and string interval values at both the API model and SQLite store boundary; no implicit integer coercion.
- Enforce the same 1-hour minimum and 365-day maximum in the persistence layer as the API contract.
- Add regression tests for invalid types, lower/upper bounds and valid boundary values.
- This protects direct/internal ScheduleStore callers as well as HTTP clients; it does not alter the supported scheduling cadence.
- GitHub Actions run [43811406822](https://github.com/justinhblee-prog/shorts/actions/runs/43811406822) passed the complete `scripts/validate.sh` workflow, including 497 backend tests.


## BUILD-00162 — bounded scheduler runtime configuration

- Replace implicit integer coercion and lower-bound clamping for scheduler polling/leader-lease environment settings with strict decimal-integer parsing.
- Bound polling to 5–300 seconds and leader lease TTL to 15–3600 seconds; reject malformed, negative, fractional, zero and out-of-range configuration at startup.
- Require the poll interval to be no more than one-third of the lease TTL so a healthy scheduler has time to renew leadership before expiry.
- Add isolated unit coverage for defaults, invalid values, bounds and poll/lease relationship.
- GitHub Actions run [43811134991](https://github.com/justinhblee-prog/shorts/actions/runs/43811134991) passed the complete validation workflow; deployment-level multi-instance behavior remains separate.


## BUILD-00163 — strict scheduler store control inputs

- Require schedule activation state to be an actual boolean at the persistence boundary; do not interpret truthy strings, integers or containers as an activation command.
- Validate outbox query and dispatch limits as non-boolean integers within explicit bounds rather than silently coercing or clamping values.
- Validate dispatch lease TTL before any database work, including empty/no-due batches, so invalid configuration cannot pass unnoticed on an idle scheduler.
- Add direct-store regression tests for all control boundaries.
- GitHub Actions run [43811522376](https://github.com/justinhblee-prog/shorts/actions/runs/43811522376) passed the complete `scripts/validate.sh` workflow, including 497 backend tests.


## BUILD-00164 — durable scheduler outbox retry backoff

- Add a nullable `next_attempt_at` field with an in-place SQLite migration for existing outbox tables.
- Apply exponential retry delays after queue-dispatch failures: 30 seconds initially, doubling per failure, capped at one hour.
- Keep deferred records visible in outbox status while excluding them from dispatch until their retry timestamp is due.
- Clear retry timestamps after successful idempotent queue acceptance.
- Add regression tests for retry timing, exponential growth/cap, and compatibility with existing pending outbox rows.
- GitHub Actions run [43811943929](https://github.com/justinhblee-prog/shorts/actions/runs/43811943929) passed the complete `scripts/validate.sh` workflow, including 500 backend tests.


## BUILD-00165 — scheduler outbox dead-letter handling

- Stop automatic retries after 10 consecutive queue-dispatch failures and move the item to `dead_letter` instead of retrying forever.
- Keep dead-letter items visible in the existing outbox status endpoint with attempt count and last error.
- Add an authenticated operator endpoint to explicitly retry a dead-letter item; reset retry state but preserve its original idempotency key.
- Add regression coverage for the retry ceiling, manual recovery, missing IDs and idempotent dispatch.
- GitHub Actions run [43812423780](https://github.com/justinhblee-prog/shorts/actions/runs/43812423780) passed the complete `scripts/validate.sh` workflow, including 503 backend tests.


## BUILD-00166 — accurate scheduler outbox readiness status

- Correct the outbox status contract: distinguish pending entries ready for dispatch from entries deferred by retry backoff.
- Calculate `pending_retries` only for pending rows whose retry timestamp is still in the future; expose `pending_ready` separately.
- Prioritize dead-letter records in the bounded operator status list so actionable failures are not hidden behind routine pending rows.
- Add deterministic clock-based tests for before/after retry eligibility and timezone validation.
- GitHub Actions run [43812695326](https://github.com/justinhblee-prog/shorts/actions/runs/43812695326) passed the complete `scripts/validate.sh` workflow, including 505 backend tests.


## BUILD-00167 — prevent dead-letter recovery for inactive schedules

- Restrict manual dead-letter retry to entries whose parent schedule is still active.
- Enforce the active-state condition atomically in the SQLite update, avoiding a check-then-update race.
- Keep inactive schedule dead-letter records visible for audit; reactivation allows an operator to retry them explicitly.
- Add regression coverage for inactive rejection and successful retry after reactivation.
- GitHub Actions run [43812864095](https://github.com/justinhblee-prog/shorts/actions/runs/43812864095) passed the complete `scripts/validate.sh` workflow, including 506 backend tests.


## BUILD-00168 — scheduler outbox operator dashboard recovery

- Show separate ready-to-dispatch, deferred-retry, dead-letter and dispatched counts in the operator dashboard.
- Display the next retry timestamp and failure count for each visible outbox record.
- Add an authenticated, confirmation-gated manual retry action for dead-letter records; the backend remains authoritative and rejects retries for inactive schedules.
- Add frontend contract tests and update the operator runbook.
- GitHub Actions run [43813399491](https://github.com/justinhblee-prog/shorts/actions/runs/43813399491) passed the complete `scripts/validate.sh` workflow, including 507 backend tests.


## BUILD-00169 — database-backed readiness probe

- Preserve `GET /api/health` as a process-liveness probe independent of downstream storage.
- Add public `GET /api/ready` that verifies the durable queue and scheduler stores can serve core reads; return HTTP 503 without exposing database errors when storage is unavailable.
- Switch the API container healthcheck and dependent service startup gates to the readiness endpoint.
- Add regression tests for ready, unavailable-storage and liveness independence behavior.
- GitHub Actions run [43813703452](https://github.com/justinhblee-prog/shorts/actions/runs/43813703452) passed the complete `scripts/validate.sh` workflow, including 510 backend tests.


## BUILD-00170 — strict production worker runtime configuration

- Validate worker lease, idle polling and heartbeat environment settings before opening the queue.
- Enforce lease 30–3600 seconds, idle polling 1–300 seconds and configured heartbeat 5–3600 seconds.
- Require unsigned decimal integer strings; reject coercions, signs, whitespace, decimal/exponent notation and out-of-range values.
- Cap effective heartbeat to one-third of the lease.
- Add pure configuration regression tests and operator documentation.
- GitHub Actions run [43814172390](https://github.com/justinhblee-prog/shorts/actions/runs/43814172390) passed the complete `scripts/validate.sh` workflow, including 514 backend tests.


## BUILD-00171 — worker heartbeat observability

- Worker registry API now returns `heartbeat_age_seconds` and `stale_after_seconds` for each worker.
- Distinguish a stale online worker from a worker that explicitly completed graceful shutdown (`offline`). Malformed heartbeat timestamps fail closed as stale.
- Operations dashboard shows worker state, last heartbeat age and stale threshold.
- Added regression tests for stale classification and preservation of explicit offline state.
- GitHub Actions run [43814901569](https://github.com/justinhblee-prog/shorts/actions/runs/43814901569) passed the complete `scripts/validate.sh` workflow, including 516 backend tests.


## BUILD-00172 — unified expired worker lease recovery

- Consolidate lease-expiry handling into one transaction-scoped resolver shared by opportunistic recovery during worker claim and periodic queue recovery.
- Apply identical retry-ceiling, terminal-state, lease-fencing and audit-event semantics regardless of which recovery path discovers the expiry.
- Keep ambiguous short-video production outcomes terminal, update the associated production run, and pause production pending explicit operator reconciliation; never replay a potentially completed provider request automatically.
- Add regression coverage for path parity, exhausted attempts, production-run synchronization, audit details and stale-worker fencing.
- GitHub Actions run [43815743528](https://github.com/justinhblee-prog/shorts/actions/runs/43815743528) passed the complete `scripts/validate.sh` workflow, including 518 backend tests.


## BUILD-00173 — operator reconciliation for ambiguous AI production outcomes

- Add an authenticated endpoint to list production jobs blocked after an ambiguous provider outcome.
- Permit a retry only when an operator explicitly confirms, with a provider-console/request evidence reference and investigation note, that no external side effect occurred.
- Authorize exactly one additional attempt without resetting historical attempt counts; keep the global production pause in place until a separate explicit resume action.
- Add append-only reconciliation audit records protected against UPDATE/DELETE and synchronize the production run state atomically with the queue transition.
- If provider history shows generation completed, the retry action is not applicable; result adoption remains a separate follow-up and no provider result is fabricated.
- GitHub Actions run [43816436787](https://github.com/justinhblee-prog/shorts/actions/runs/43816436787) passed the complete `scripts/validate.sh` workflow, including 520 backend tests. The earlier run exposed an optional-schema assumption in the reconciliation listing query; the query was narrowed to durable queue columns and the full suite passed on the corrected commit.


## BUILD-00174 — durable provider response recovery ledger

- Persist a per-stage provider attempt before each outbound AI request, with monotonic attempt number and unique request key.
- Persist complete provider JSON response before artifact-row persistence, so a worker crash between provider response and local artifact adoption does not erase the returned output.
- Record transport failures as `outcome_unknown`; never infer that a provider did not execute from a timeout.
- Allow late provider response/unknown-state journaling after lease expiry while keeping production artifact writes lease-fenced.
- Add authenticated `GET /api/production/jobs/{job_id}/provider-attempts` for operator recovery and bounded response storage.
- The provider idempotency key is advisory unless a vendor contract confirms support. Automated result adoption is intentionally not included; recovered outputs still require provider verification, allowlisted media staging, quality checks and human review.
- GitHub Actions run [43817538942](https://github.com/justinhblee-prog/shorts/actions/runs/43817538942) passed the complete `scripts/validate.sh` workflow, including 525 backend tests.


## BUILD-00175 — verified adoption of recovered provider renders

- Add operator-only adoption endpoint for a stored rendering response; arbitrary caller-supplied URLs are not accepted.
- Download through the existing HTTPS host allowlist, DNS/IP validation, redirect rejection, bounded staging and optional malware scanning.
- Inspect actual staged bytes with ffprobe; reject missing inspection, non-vertical output, absent audio, invalid duration or oversized/invalid staged fingerprints.
- Atomically insert the recovered video artifact, mark the provider attempt adopted, update production and queue jobs to `review_pending`, and record a queue audit event.
- Block duplicate adoption, active worker jobs and replacement of approved/uploaded/published outputs.
- Human review and explicit publication approval remain mandatory; no automatic approval or posting.
- GitHub Actions run [43817903769](https://github.com/justinhblee-prog/shorts/actions/runs/43817903769) passed the complete `scripts/validate.sh` workflow, including 525 backend tests. The recovered-output path also rebuilds a fresh quality report from the stored script/voice metadata and byte-level media inspection before queueing review.


## BUILD-00176 — recovered output provenance in review workspace

- Show a distinct recovered-provider-result notice in the pending-review card.
- Display provider attempt ID, staged media filename, SHA-256 and byte size from the recovered artifact metadata.
- Explicitly state that recovery and automated file inspection do not constitute human approval or permission to publish.
- Add frontend regression coverage for provenance and review-boundary messaging.
- GitHub Actions run [43818084149](https://github.com/justinhblee-prog/shorts/actions/runs/43818084149) passed the complete `scripts/validate.sh` workflow, including 526 backend tests.


## BUILD-00177 — atomic review decision synchronization and publication boundary

- Synchronize an operator's approve/reject/revision decision from `production_runs` to the matching durable `pipeline_jobs` row in the same SQLite transaction.
- Fail closed if an existing production queue row is not a `short_video_production` job in `review_pending`; the production decision and append-only review record roll back together.
- Append a queue `job_events` audit event with the operator identity and decision context for every synchronized decision.
- Add regression tests for approval/rejection synchronization, audit provenance, and queue-state mismatch rollback.
- Preserve the separate publication boundary: approval alone does not invoke YouTube/TikTok publishers; platform upload remains a distinct explicit operator action with its own artifact-integrity, policy and platform-specific gates.
- Automated tests use local SQLite/fake provider fixtures only; no live YouTube/TikTok account or external AI provider validation is claimed.
- GitHub Actions runs [43820319862](https://github.com/justinhblee-prog/shorts/actions/runs/43820319862) and [43820326868](https://github.com/justinhblee-prog/shorts/actions/runs/43820326868) passed the complete `scripts/validate.sh` workflow, including 530 backend tests. The initial run exposed the expected second-review transition after media staging; the queue is now explicitly reopened with an audit event before fresh approval.


- Follow-up hardening: when an approved production is explicitly returned to `review_pending` for a new artifact/review pass, atomically reopen its queue row and append a `review_reopened` event. This supports a fresh approval after media staging or artifact changes without leaving the queue falsely approved.
- The full lifecycle regression exercises the two-review cycle (initial review, exact media staging, fresh review, private upload).


## BUILD-00178 — production lifecycle state integrity monitor

- Add a bounded lifecycle consistency scan before the worker claims new production work.
- Automatically repair only two deterministic crash windows: queue cancellation/terminal failure not yet mirrored to production, and completed queue review handoff where production remains `rendered`.
- Record each automatic repair as an immutable-in-practice queue event with source and before/after states.
- Never guess or auto-promote approval/upload states. Any unresolved mismatch pauses the worker before another provider job can be claimed and requires operator investigation.
- Regression tests cover safe repair, unresolved approval mismatch, idempotency, and shared-database enforcement.
- GitHub Actions runs [43821783189](https://github.com/justinhblee-prog/shorts/actions/runs/43821783189) and [43821793079](https://github.com/justinhblee-prog/shorts/actions/runs/43821793079) passed the complete `scripts/validate.sh` workflow, including 533 backend tests each. Earlier failing runs exposed fixture assertions that omitted the pre-existing enqueue audit event; assertions were corrected to verify exactly one reconciliation event without discarding the enqueue event.


## BUILD-00179 — operator production integrity report

- Add a read-only, bounded `GET /api/production/integrity-report` endpoint protected by the existing `production.read` operator permission.
- Report mismatched production/queue states with both ledger timestamps, queue error context, bounded audit history, a classification, and a safe next action.
- Redact unapproved event-detail fields from the report; never expose provider response payloads or arbitrary event JSON.
- Explicitly flag approval/upload boundaries and ambiguous external outcomes. The report never repairs state, authorizes retry, resumes workers, or publishes content.
- Reuse the existing evidence-backed `/api/production/jobs/{job_id}/reconcile-retry` and separate audited queue-resume workflows rather than introducing a competing state override.
- Regression tests verify read-only behavior, audit-detail filtering, bounded results, and same-database enforcement.


## BUILD-00180 — operator integrity dashboard

- Connect the BUILD-00179 read-only integrity report to the Operations workspace.
- Show the bounded mismatch count, queue pause state, both ledger states/timestamps, classifications, safe recommended action, queue error context, and recent audit event chronology.
- Escape all dynamic content before rendering; no status-change, retry, approval, resume, upload, or publish control is exposed in this diagnostic panel.
- Load the report during authenticated dashboard refresh and provide an explicit manual refresh action.
- Add frontend regression coverage for endpoint wiring, diagnostic content, and read-only boundaries.


## BUILD-00181 — integrity report endpoint authorization regression

- Add a direct endpoint regression test using configured per-operator credentials and role mapping.
- Verify a reviewer with `production.read` can retrieve the report, an analyst without that permission receives HTTP 403, and a missing token receives HTTP 401.
- Assert the underlying report store is never called for denied or unauthenticated requests.
- Preserve the read-only behavior: the endpoint has no state mutation path.


## BUILD-00182 — detect orphaned lifecycle records

- Extend the bounded integrity report to detect queue-only and production-only records in addition to status mismatches.
- Keep orphan diagnostics read-only; do not fabricate or delete either ledger row.
- Pause the production worker when an orphan remains after the existing validated queue-to-production recovery attempt.
- Add tests for both orphan directions, bounded scanning, and non-mutation.


## BUILD-00183 — accurate bounded integrity totals

- Calculate total mismatch, queue-only, and production-only record counts independently of the returned sample limit.
- Return accurate unresolved/orphan totals, per-class counts, and a `has_more` indicator while keeping detail rows bounded.
- Prioritize orphan records in the returned sample so the worker's bounded fail-closed check cannot overlook them behind newer state mismatches.
- Update the Operations panel to distinguish total unresolved records from the number of displayed details.
- Extend tests to verify aggregate counts and orphan prioritization under a restrictive sample limit.


## BUILD-00184 — paginated integrity details

- Add a bounded offset parameter to the integrity report while preserving aggregate counts and orphan-first ordering.
- Return page offset and next offset so operators can inspect all matching details without increasing per-request row limits.
- Add a dashboard **다음 50건 더 보기** control that appends the next page without discarding the current page.
- Add regression coverage for complete, non-overlapping pagination.


## BUILD-00185 — stable cursor pagination

- Add opaque keyset cursors ordered by immutable record group and job ID, avoiding offset-page duplicates/skips when an existing record's updated timestamp changes.
- Retain bounded offset pagination for backward compatibility; the Operations dashboard now uses cursor pagination.
- Reject malformed cursor tokens and test cursor continuity under mutable record timestamps.


## BUILD-00186 — batched integrity audit history

- Replace per-record audit-history queries with one bounded page-level query.
- Use a per-job window rank to retain only the 10 newest events for each displayed record.
- Preserve chronological presentation and the existing safe-field allowlist.
- Add regression coverage for the per-job 10-event cap and ordering.


## BUILD-00187 — redact raw queue error details

- Stop exposing raw provider/worker error text through the production integrity report.
- Preserve the controlled error code and return a fixed instruction to inspect protected server logs.
- Add a regression test using a bearer-token-like secret in the stored error message.


## BUILD-00201 — fence YouTube upload reservations by current queue approval

- Require the real YouTube publisher to re-read the durable `short_video_production` queue row inside the same `BEGIN IMMEDIATE` transaction that reserves an upload attempt.
- Reject missing queue rows, wrong job types, and queue states other than `approved`, even when the production ledger and latest human decision still appear approved.
- Preserve the low-level store default for fixture/metrics seeding; the actual publisher always enables strict current-approval validation.
- Add regressions for queue reopening and queue-row deletion immediately before upload reservation.
- Keep YouTube visibility private; no public publishing behavior is introduced.


## BUILD-00202 — direct expired-lease operation fencing regressions

- Add direct-expiry regression coverage for all three worker-owned lease operations: heartbeat, finish, and fail.
- Expire a claimed lease without allowing another worker to reclaim it, then assert each stale operation raises `LeaseConflict`.
- Verify rejected stale operations leave the running row, worker ownership, and lease token unchanged.
- This validates the existing transactional lease-expiry guard independently of the separate reclaim path.


## BUILD-00203 — scheduled dispatch through private YouTube lifecycle E2E

- Extend the integrated lifecycle test to start from a persisted production schedule rather than direct submission.
- Acquire the scheduler leader lease, dispatch the due occurrence through the durable outbox, and assert idempotent second dispatch.
- Exercise worker-startup reconciliation that restores the production ledger row from the scheduled queue job before claim.
- Continue through provider generation, human review, staged-media reapproval, private YouTube upload, and finance-ledger recording.
- All external AI/CDN/YouTube behavior remains explicitly mocked; this is an integration contract test, not live-service validation.


## BUILD-00204 — block retries while provider outcomes are unresolved

- Make provider attempt reservation reject a new attempt when the same job/stage has a prior `request_started`, `outcome_unknown`, or `response_received` attempt.
- Keep the check inside the same immediate SQLite transaction as attempt reservation, preventing concurrent retry races.
- Add regression coverage for process-crash-in-flight, ambiguous transport timeout, and durable response-not-yet-adopted states.
- This deliberately fails closed rather than risking duplicate paid AI/provider side effects; recovery or operator reconciliation must happen before retry.


### BUILD-00204 recovery follow-up

- Pipeline resume now reads a durable `response_received` provider journal before reserving a new attempt.
- Script, voice, and render stages can reuse the exact persisted response after a process interruption; normal artifact persistence then marks that attempt `adopted`.
- This avoids a second paid external request when the provider response was saved but local artifact adoption had not completed.
- `request_started` and `outcome_unknown` remain fail-closed; they still require explicit reconciliation because the provider outcome cannot be inferred safely.


## BUILD-00205 — audited provider outcome reconciliation

- Add an admin-only API permission `production.provider_reconcile` for ambiguous provider attempts.
- An operator must explicitly confirm that the provider did not execute, and supply operator identity, evidence reference, and a reason.
- Persist the state transition and audit event in one SQLite transaction.
- Reconciliation does not itself retry the job; queue retry remains a separate, explicit operator action.
- `response_received` cannot be dismissed through this route; it must be recovered and adopted.


## BUILD-00206 — scheduled lifecycle through TikTok SELF_ONLY publication

- Extend the scheduled production lifecycle integration test to include both YouTube private upload and TikTok private-only upload from the same freshly staged and re-approved media artifact.
- Exercise TikTok's explicit operator consent, current approval/queue revalidation, AIGC disclosure evidence, creator privacy capability check, upload initialization and media transfer.
- Assert the TikTok request explicitly selects `SELF_ONLY`, records the operator-consent audit event, and does not invoke public posting.
- TikTok creator and upload transport plus media inspection are deterministic test doubles. This is a local integration contract test, not live TikTok OAuth/API validation.
- GitHub Actions run [43844384565](https://github.com/justinhblee-prog/shorts/actions/runs/43844384565) passed the complete `scripts/validate.sh` workflow, including 575 backend tests.


## BUILD-00207 — TikTok terminal status confirmation and duplicate-action idempotency

- Extend the scheduled multi-platform lifecycle integration test to poll TikTok's creator status after upload and persist the terminal `PUBLISH_COMPLETE` result with its video ID.
- Repeat the operator publish action after confirmation and assert the durable result is returned without another TikTok initialization or media transfer request.
- This closes the mocked end-to-end path from schedule dispatch through human approval, explicit SELF_ONLY upload, remote status confirmation and duplicate-action suppression.
- TikTok API transport and media inspection remain deterministic test doubles; no live OAuth/account validation is claimed.
- GitHub Actions run [43844733746](https://github.com/justinhblee-prog/shorts/actions/runs/43844733746) passed the complete `scripts/validate.sh` workflow, including 575 backend tests.


## BUILD-00208 — TikTok ambiguous request and chunk-upload retry fencing

- Add regressions for a lost response during TikTok publish initialization and a lost response during media chunk upload.
- Both cases must persist `reconciliation_required`, retain any known `publish_id`, and block a second publish initialization or upload request until explicit operator reconciliation.
- These tests complement YouTube's existing ambiguous resumable-upload timeout/reconciliation tests and TikTok's existing status-poll and terminal-state protections.
- Validation uses deterministic transport doubles; it does not constitute live TikTok or YouTube service validation.
- GitHub Actions run [43845160197](https://github.com/justinhblee-prog/shorts/actions/runs/43845160197) passed the complete `scripts/validate.sh` workflow, including 577 backend tests.


## BUILD-00209 — cross-platform publishing recovery contract

- Add `docs/PLATFORM_PUBLISHING_RECOVERY.md` with a shared failure/recovery matrix for preflight failures, ambiguous remote dispatch, YouTube resumable uploads, TikTok initialization/chunk transfer, status polling, inbox handoff, terminal completion, and evidence-backed reconciliation.
- Make the distinction explicit between an AI-provider reconciliation workflow and platform-publishing reconciliation; do not imply that BUILD-00205 implements the latter.
- Define retry authorization as a separate operator action after affirmative non-execution evidence, current approval/artifact revalidation, and platform-specific privacy/consent checks.
- Record the validation boundary: deterministic CI doubles do not establish live OAuth, account permission, actual upload, or production recovery readiness.
- Documentation-only change; no new runtime behavior or test result is claimed.


## BUILD-00210 — bind platform reconciliation identity to authenticated operator

- Bind YouTube upload reconciliation, YouTube late-success resolution, and TikTok publication reconciliation to the authenticated principal returned by the `publish.reconcile` permission check.
- Reject request-body operator IDs that differ from the authenticated principal before mutating publication state or writing reconciliation audit events.
- Add API-level regressions for spoofed operator identities and for matching authenticated identities on both platform reconciliation endpoints.
- This prevents an authorized reviewer from attributing a platform reconciliation audit event to an arbitrary operator ID.
- GitHub Actions validation was triggered for the initial implementation commit; confirm the final branch-head run before treating this change as validated.


## BUILD-00211 — lock platform reconciliation confirmation gates with API regressions

- Add API-level regressions proving YouTube reconciliation rejects an unconfirmed outcome before calling the store.
- Add API-level regression proving TikTok's explicit-confirmation requirement is enforced by its reconciliation store and surfaced as a conflict; the mocked store confirms the route does not bypass or reinterpret that contract.
- Add API-level regression proving a YouTube `uploaded` reconciliation cannot proceed without a verified video ID.
- No production runtime behavior changed; the change adds regression coverage for existing fail-closed validation.

## BUILD-00212 — Bind platform reconciliation to an explicit attempt identity
- YouTube upload reconciliation and late-success resolution API requests now require an `attempt_id`; TikTok publication reconciliation does the same.
- API handlers forward the supplied attempt identity to the transactional store. The store compares it with the selected current/late-success attempt before changing publication state or writing reconciliation audit events.
- Added regression tests proving stale YouTube and TikTok attempt IDs leave the uncertain state and audit history unchanged.
- This is a contract-level and deterministic SQLite test improvement; it does not constitute live YouTube/TikTok account verification.

## BUILD-00213 — Compare-and-set YouTube reconciliation attempt
- YouTube reconciliation now includes the locked row's `attempt_id` in both terminal-state UPDATE predicates, in addition to the job ID and allowed source statuses.
- This aligns YouTube's final state mutation with TikTok's existing attempt-scoped compare-and-set and makes the attempt ownership invariant explicit at the SQL write boundary.
- Extended the stale-attempt regression to prove a stale ID leaves state/audit unchanged while the matching ID can resolve the same uncertain attempt.
- Deterministic SQLite regression only; no live YouTube API validation is implied.

## BUILD-00214 — Fence TikTok status refresh writes
- TikTok status polling now applies its state update only when both the expected `attempt_id` matches and the row remains non-terminal.
- The store checks the affected-row count before appending a status-refresh audit event. If the compare-and-set does not apply, it returns an already-terminal result for the same attempt or raises a state-change error without writing a misleading audit event.
- Added a SQLite trigger regression that suppresses the attempted state update and verifies state and audit history remain unchanged.
- Deterministic local database validation only; no live TikTok API verification is implied.

## BUILD-00215 — Fence TikTok poll responses by source state
- A TikTok status poll now carries both the publication `attempt_id` and the state observed before the remote request.
- The returned status is applied only if the same attempt is still in that source state. A response that arrives after another poll or recovery action changed the state is rejected without changing the publication row or appending a status-refresh event.
- Added a regression for a late completion response arriving after the publication has already advanced to processing.
- Deterministic local database validation only; no live TikTok API verification is implied.

## BUILD-00216 — Fence TikTok poll-error backoff by source state
- Scheduler status-poll failures now carry the publication state observed before the poll began.
- A delayed poll error is ignored if the same attempt has since moved to another state; it cannot refresh retry backoff timestamps or append a misleading retry-scheduled event.
- Added a regression verifying stale poll errors leave status, update timestamp, and event history unchanged.
- Deterministic local database validation only; no live TikTok API verification is implied.

## BUILD-00217 — Fence TikTok timeout uncertainty transitions
- A delayed publish/init transport timeout may move a TikTok attempt to `reconciliation_required` only while that attempt is still `initializing` or `uploading`.
- If a concurrent status poll has already advanced the same attempt to `processing` or another state, the timeout is ignored and no stale uncertainty audit event is appended.
- Added a regression where a late transport timeout arrives after TikTok has confirmed processing.
- Deterministic local database validation only; no live TikTok API verification is implied.

## BUILD-00218 — Verify superseded YouTube uncertainty remains fail-closed
- A late failure from a superseded upload attempt can still represent an unresolved remote outcome; the job remains blocked for operator reconciliation rather than allowing a potentially duplicate retry.
- The current row retains the newer attempt identity while the uncertainty audit event retains the superseded attempt identity.
- Extended the regression to assert both identities remain distinct and correctly recorded.
- Deterministic local database validation only; no live YouTube API verification is implied.

## BUILD-00219 — Block TikTok retries after superseded-attempt uncertainty
- A late transport failure from a previously reconciled TikTok attempt is no longer silently discarded when a newer attempt has started.
- The old attempt identity and its own publish/video identifiers are preserved in a `superseded_attempt_uncertain` audit event, while the current publication is moved to `reconciliation_required` without replacing its current attempt ID.
- Terminal current outcomes are preserved and receive informational audit evidence only.
- Added a regression covering operator-confirmed no-publication, a subsequent retry reservation, and a delayed uncertainty from the superseded attempt.
- Deterministic local database validation only; no live TikTok API verification is implied.

## BUILD-00220 — Preserve non-null TikTok superseded-attempt audit identifiers
- Superseded-attempt uncertainty now retrieves the latest non-null publish ID, video ID, and operator ID independently instead of relying on the newest event row to contain all metadata.
- Added a regression with a later diagnostic event containing null provider identifiers, verifying the earlier publish ID remains attached to the delayed uncertainty event.
- Deterministic local database validation only; no live TikTok API verification is implied.

## BUILD-00221 — Audit superseded YouTube worker errors during late-success review
- A delayed worker failure received while a job is already in `late_success_review_required` is now retained as an informational audit event instead of being silently discarded.
- The event distinguishes a current-attempt post-confirmation error from a superseded-attempt uncertainty and preserves the existing late-success review state, current attempt ID, and recorded video ID.
- Added a regression covering late remote success followed by a delayed worker error from the superseded attempt.
- Deterministic SQLite validation only; no live YouTube API verification is implied.

## BUILD-00222 — Preserve canonical video IDs in YouTube worker-error audit events
- Post-confirmation worker-error events now retain the canonical video ID already recorded on the upload row, both after successful upload and while late-success review is pending.
- This avoids audit events that identify the attempt but omit the remote video already associated with it.
- Regression asserts the late-success review event carries the preserved video ID.
- Deterministic backend CI only; no live YouTube API verification.

## BUILD-00223 — Preserve TikTok provider identifiers in nonterminal uncertainty events
- Superseded-attempt uncertainty events that block a newer nonterminal attempt now retain the prior attempt's video ID as well as its publish ID and operator ID.
- The event query already retrieves the latest non-null provider identifiers independently, so the audit row now persists all of them consistently in both terminal and nonterminal branches.
- Regression asserts the publish ID and operator identity survive a later diagnostic row with null provider identifiers.
- Backend deterministic CI only; no live TikTok API verification.

## BUILD-00224 — Retain attempt-specific YouTube video IDs in superseded worker audit events
- Superseded YouTube worker errors now look up the latest non-null video ID belonging to that exact attempt and retain it in informational audit events after a newer attempt has already uploaded.
- The canonical current upload row remains unchanged; the audit event records the old attempt's own remote video identifier.
- Added regression coverage for a late superseded worker error after a newer upload has completed.
- Backend deterministic CI only; no live YouTube API verification.

## BUILD-00225 — Prevent cross-attempt YouTube video ID fallback
- When a superseded attempt has no recorded provider video ID, its informational worker-error audit event now keeps video_id null instead of borrowing the current attempt's video ID.
- Added a regression proving the canonical current upload remains intact while the superseded attempt's audit event does not misattribute the newer video's identifier.
- Backend deterministic CI only; no live YouTube API verification.

## BUILD-00226 — Prevent cross-attempt TikTok operator attribution
- When a superseded TikTok attempt has no recorded operator identity, its uncertainty audit event now keeps operator_id null rather than borrowing the current attempt's operator.
- Added regression coverage for an old attempt with missing operator metadata while a newer attempt has a distinct operator.
- Backend deterministic CI only; no live TikTok API verification.

### BUILD-00226 validation correction
- The first regression draft attempted to mutate an immutable audit row and correctly failed the repository's append-only audit trigger.
- Reworked the fixture to create an attempt with no consent operator identity, then reconcile it under a separate reviewer identity. The lookup now derives attempt ownership only from the immutable consent event, not from later reviewer/audit actors.
- This prevents both cross-attempt attribution and misclassification of a reconciliation reviewer as the original publisher.

## BUILD-00227 — Audit late provider statuses from superseded TikTok attempts
- A TikTok status poll can finish after the original attempt was reconciled and a newer attempt began. Previously the stale attempt ID caused the provider result to be rejected without preserving a late PUBLISH_COMPLETE/video ID.
- The store now appends the late result to the original attempt's audit history and retains its publish ID, video ID, and original consent operator. It never overwrites the newer attempt's identity or video fields.
- Late published/processing outcomes move a nonterminal current row to reconciliation_required, blocking another retry until an operator verifies the remote account. Existing terminal current outcomes remain intact.
- Added regression coverage. Backend deterministic CI only; no live TikTok API verification.

- Follow-up boundary check: a newer attempt in the retryable `failed` state is not treated as terminal when an older attempt later reports processing/published. It is moved to reconciliation_required, consistent with the superseded-uncertainty policy.

## BUILD-00228 — Preserve old YouTube video IDs when superseded worker errors arrive during a retry
- When an old worker reports an uncertain result while a newer attempt is actively uploading, the audit event now retains the latest non-null video ID belonging to the old attempt.
- The newer attempt's canonical video_id remains untouched; missing old IDs remain null rather than borrowing the new attempt's value.
- Added regression coverage and updated BUILD_STATUS. Backend deterministic CI only; no live YouTube API verification.

## BUILD-00229 — Verify safe late TikTok failure statuses do not block a newer attempt
- Added regression coverage for a delayed FAILED status from a superseded attempt.
- The old failure is appended to the old attempt's audit trail with its publish ID and original consent operator; the active new attempt remains initializing and its identity/video fields remain unchanged.
- This distinguishes a provider-confirmed old failure from late PROCESSING/PUBLISH_COMPLETE outcomes, which correctly require reconciliation and block retry.
- Backend deterministic CI only; no live TikTok API verification.

## BUILD-00230 — Treat late TikTok inbox delivery as a remote side effect
- Extended superseded-attempt status fencing to include `SEND_TO_USER_INBOX`. Although this is not a published-feed completion, it still delivers content to the creator's inbox and must not be treated as a safe no-side-effect failure.
- A late inbox-delivery result from an older attempt is preserved in that attempt's audit trail and moves a retryable current attempt to `reconciliation_required`, preventing duplicate delivery.
- Added regression coverage for late inbox delivery after a newer attempt failed preflight. Backend deterministic CI only; no live TikTok API verification.

## BUILD-00231 — Verify YouTube late success after a newer upload preserves both video IDs
- Added a regression where attempt A is explicitly reconciled as not uploaded, attempt B completes, and then A's delayed success response arrives.
- The current row retains attempt B's canonical video ID and attempt identity, while attempt A's late video ID is retained only in A's audit event.
- The job transitions to `late_success_review_required` and another retry remains blocked until operator resolution, preventing a duplicate upload.
- Backend deterministic CI only; no live YouTube API verification.

## BUILD-00232 — Preserve expired lease owner in recovery audit
- Expired-lease recovery previously cleared `worker_id` from the queue row and wrote a `lease_expired` event with a null worker, losing which worker owned the expired lease.
- Recovery now snapshots the owner before clearing the lease and records it as the event actor and `expired_worker_id` detail. Lease tokens are intentionally not written to audit logs.
- Added assertions for ordinary retryable/exhausted jobs and ambiguous production leases across both claim-triggered and periodic recovery paths.
- Backend deterministic CI only; no external provider validation.

## BUILD-00233 — Verify concurrent expired-lease recovery is idempotent
- Added an eight-way concurrent recovery regression against one expired ordinary job.
- Exactly one recovery call may requeue the job and append the `lease_expired` audit event; all other recovery calls must observe the committed state and do nothing.
- The original worker's lease token remains fenced after recovery. This validates the existing SQLite `BEGIN IMMEDIATE` transaction and conditional row update under concurrent callers.
- Backend deterministic CI only; no multi-host production database test is claimed.

## BUILD-00234 — Verify heartbeat and expired-lease recovery fencing
- Added a lifecycle regression covering a valid heartbeat extension, a later expired-lease recovery, and a new worker claiming the requeued job.
- The original worker's heartbeat is rejected both immediately after recovery and after the new worker claims the job; it cannot overwrite the new owner's lease.
- Confirms a valid heartbeat prevents premature recovery and that rejected stale heartbeats do not create heartbeat audit events or mutate the new lease.
- Backend deterministic CI only; no multi-host production database test is claimed.


## BUILD-00235 — Evaluate worker lease clocks after transaction lock
- Moved lease timestamps for claim, heartbeat, completion, failure, and periodic recovery inside the `BEGIN IMMEDIATE` transaction, after SQLite grants the write lock.
- Prevents lock contention from making a heartbeat or completion validate against a timestamp captured before the lease actually expired; prevents newly claimed leases from losing their duration while waiting for the lock.
- Added a deterministic lock-contention regression: advance the clock beyond expiry while heartbeat is blocked on the write lock and verify the stale heartbeat is rejected without an audit event or lease mutation.
- Backend deterministic CI only; no multi-host production database test is claimed.


## BUILD-00236 — Fence worker registry and control timestamps
- Extended the post-lock timestamp rule to pause, resume, worker registration, and worker-offline transitions.
- These operations now obtain the SQLite write lock before capturing their audit/heartbeat timestamp, preventing lock waits from writing out-of-order timestamps or stale worker liveness values.
- Combined with BUILD-00235, all lease/control/registry state transitions that acquire the SQLite write lock use a timestamp observed after lock acquisition.
- Backend deterministic CI only; no multi-host production database test is claimed.


## BUILD-00237 — Fence worker registry by process generation
- Each worker registration now receives a fresh random generation token, including when a worker_id is reused after restart.
- Graceful offline transitions require the generation token and use a conditional update; a late shutdown from an older process cannot mark the replacement process offline.
- Existing worker_registry databases receive an additive nullable column migration. Legacy offline calls without a generation token fail closed.
- Added regressions for stale-generation shutdown and missing generation tokens.
- Backend deterministic CI only; no multi-host production database test is claimed.


## BUILD-00238 — Bind Worker generation to process lifetime
- Worker runtime registers exactly once at process startup and retains that returned generation token for graceful shutdown.
- Removed per-poll registration, which would otherwise rotate the token repeatedly and make process-scoped fencing meaningless.
- Shutdown now supplies the retained token; stale process shutdown is rejected by the registry compare-and-set.
- CI validates repository tests; no real multi-process production deployment is claimed.


## BUILD-00239 — Fence queue lease operations by worker generation
- Added generation checks inside the same SQLite write transaction for claim, heartbeat, finish, and fail.
- The worker runtime passes its process-scoped generation token through each lease operation.
- Queue claim preserves the registered generation instead of replacing it with a fresh token.
- Added regression coverage proving a replaced process cannot claim work, heartbeat, finish, or fail a lease owned under its old generation.
- CI remains the deterministic validation boundary; no live multi-process production test is claimed.


## BUILD-00240 — Fence worker-originated global pause
- Worker-triggered global pause requests now carry the process generation token and worker ID.
- The queue validates that generation under the same SQLite write lock before changing global pause state or fencing active jobs.
- Operator/system pause calls without a worker generation remain supported as explicit control-plane actions.
- Added regression coverage: a replaced process cannot pause the replacement's queue; the current generation can still pause it.
- Automated CI is the validation boundary; no production multi-host race test is claimed.


## BUILD-00241 — Race worker restart against expired lease recovery
- Added a concurrent regression that releases worker re-registration and expired-lease recovery together against the same SQLite queue.
- Verifies the expired job is requeued exactly once, only one lease-expired audit event is emitted, the replacement generation remains online, and the old process cannot mark it offline or heartbeat its stale lease.
- Confirms the replacement generation can claim the recovered job after the race.
- This is deterministic local SQLite concurrency coverage; it is not a claim of multi-host production validation.


## BUILD-00242 — Require generation proof for registered worker mutations
- Closed a fencing bypass where callers could omit the generation token after a worker ID had been registered.
- Registered worker IDs now require a matching, online generation for claim, heartbeat, finish, fail, and worker-originated pause operations.
- Unregistered legacy/test queue usage remains supported; explicit operator/system pause without worker identity remains supported.
- Added regression coverage for omitted-token bypass attempts and verifies no lease or queue-control state changes.


## BUILD-00243 — Concurrent platform publish reservation
- Added concurrent same-job reservation tests for YouTube private uploads and TikTok SELF_ONLY publication.
- Eight simultaneous reservation attempts must produce exactly one durable attempt and one start/consent audit record; all competing requests are rejected without replacing the winning attempt.
- Confirms TikTok reservation remains SELF_ONLY.
- Deterministic SQLite transaction tests only; no live platform API or account validation is claimed.

## BUILD-00249 — Serialize YouTube failure finalization
- Acquire SQLite's immediate write lock before capturing the failure timestamp and updating the matching upload attempt.
- Preserve attempt fencing and write the failure audit only when the active attempt transitions from uploading to failed.
- Regression verifies one failure audit and that a delayed stale failure cannot downgrade a newer uploading attempt.
- Deterministic local SQLite validation only; no live YouTube API test is claimed.


## BUILD-00264 — Revalidate YouTube metrics lease after OAuth initialization
- Move the final metrics-collector lease assertion to after service/OAuth initialization and immediately before the outbound YouTube Data API request, for both batch polling and manual refresh.
- OAuth token refresh or client construction can block long enough for the lease to expire or be replaced; the prior pre-initialization assertion left a window in which a stale collector could still issue a quota-consuming request.
- Add batch and manual regressions that replace the lease during service initialization and verify no YouTube list request is sent.
- Deterministic local SQLite/fake-service CI only; no live YouTube OAuth or API validation is claimed.


## BUILD-00265 — Fence YouTube Analytics provider calls by collector lease
- Add an explicit live-lease assertion after OAuth/service initialization and immediately before each Analytics API request.
- Revalidate between watch-time and retention requests so a collector that loses ownership cannot issue the second request.
- Propagate lease-loss exceptions out of the batch loop rather than continuing to initialize clients or request later videos under stale ownership.
- Add regressions for takeover during OAuth initialization, lease loss between report requests, and batch termination.
- GitHub Actions run #3474 succeeded on commit `5516b913382aec51a4614b03c02b6462e559bee9` (job `test`; `scripts/validate.sh` passed). Tests use local SQLite and fake report services. No live YouTube OAuth/API verification is claimed.


## BUILD-00266 — Reject stale YouTube Analytics collectors before OAuth refresh
- Validate the collector lease before constructing the Analytics service. OAuth credential refresh can itself make an outbound token request, so a worker whose lease is already expired/replaced must not reach that initialization path.
- Retain the post-initialization lease check immediately before the Analytics report request, because OAuth/client setup can outlive the lease.
- Add a regression that expires the lease before collection and proves service/OAuth initialization is never invoked.
- GitHub Actions [run #3479](https://github.com/justinhblee-prog/shorts/actions/runs/43912866442) succeeded on commit `7ee9ffe69d833c57680a934abb2c61da09316655`; `scripts/validate.sh` passed. Deterministic local SQLite/service-stub CI only; no live YouTube OAuth or Analytics API validation is claimed.


## BUILD-00267 — Verify YouTube Analytics heartbeat lease-loss handling
- Add scheduled-collector regressions where lease renewal succeeds before collection but fails immediately after the provider batch returns; completed results must not be persisted as success.
- Cover provider-error handling when the lease is lost concurrently; the stale worker must not write a failed collection state either.
- Verify the collector releases only its own lease in both cases.
- GitHub Actions [run #3484](https://github.com/justinhblee-prog/shorts/actions/runs/43913434527) succeeded on commit `22f456ea042f1441917b9c56e872aff4bd030b41`; `scripts/validate.sh` passed. Mocked-store/collector tests only; no live YouTube OAuth or Analytics API validation is claimed.


## BUILD-00268 — Fence TikTok metrics OAuth refresh and provider dispatch
- Expose a read-only lease assertion for the TikTok metrics collector.
- Reject an already-expired/replaced collector before invoking the OAuth token provider, because token refresh may itself make an outbound request.
- Revalidate after token acquisition and immediately before the TikTok Display API request to cover lease loss during OAuth refresh.
- Add regressions for a stale lease before OAuth initialization and lease replacement during token refresh; both must prevent the Display API transport call.
- GitHub Actions [run #3490](https://github.com/justinhblee-prog/shorts/actions/runs/43913802483) succeeded on commit `5edfebbfdb2c07450038c56f53be31816b680f9a`; `scripts/validate.sh` passed. Tests use local SQLite and fake token/transport providers; no live TikTok OAuth/account/API validation is claimed.


## BUILD-00269 — Verify TikTok metrics heartbeat lease-loss handling
- Add scheduled TikTok metrics collector regressions for lease loss after a successful provider batch and during provider-error handling.
- Ensure stale workers cannot persist either a success or failed collection state after lease renewal fails.
- Verify the worker still attempts to release its own lease during cleanup.
- GitHub Actions [run #3493](https://github.com/justinhblee-prog/shorts/actions/runs/43914162222) succeeded on commit `f939df3e5ff72723f96d5ac5942b8f78c202fc8e`; `scripts/validate.sh` passed. Tests use fake stores and collectors; no live TikTok OAuth/account/API validation is claimed.


## BUILD-00270 — Verify provider collection-cycle failure isolation
- Extract one scheduled metrics collection cycle so the provider isolation policy can be tested directly.
- Add a regression proving a YouTube provider exception is logged while YouTube Analytics and TikTok collectors still run in the same cycle.
- Verify process-control exceptions such as KeyboardInterrupt are not swallowed by the provider-failure handler.
- GitHub Actions [run #3498](https://github.com/justinhblee-prog/shorts/actions/runs/43914864286) succeeded on commit `edc28c34ec29c1daeeb95e9c8223ba45b82a93d2`; `scripts/validate.sh` passed. This is deterministic local unit coverage; no live provider API validation is claimed.


## BUILD-00271 — Run independent metrics providers concurrently
- Run YouTube Data API, YouTube Analytics, and TikTok metrics collectors in independent worker threads during each collection cycle.
- Preserve per-provider exception isolation and wait for all providers to finish before the cycle returns.
- Process-control exceptions remain uncaught by the provider isolation handler.
- Add synchronization-based tests proving provider overlap and cycle completion semantics.
- GitHub Actions [run #3497](https://github.com/justinhblee-prog/shorts/actions/runs/43915500121) succeeded on commit `abd89828e6a451790baa037f1461ff8a4d1768d9`; `scripts/validate.sh` passed. Tests use local fakes; no live provider API validation is claimed.


## BUILD-00272 — Wait for worker heartbeat thread termination
- Remove the five-second bounded join from the production worker's heartbeat cleanup.
- A heartbeat may be blocked inside SQLite's configured 30-second busy timeout; clearing the active job context or proceeding to another claim while it is still alive can let a stale heartbeat race with subsequent worker lifecycle actions.
- Wait for the heartbeat thread to exit before clearing active-job state.
- Add a regression that blocks the heartbeat database call and asserts cleanup joins without a timeout.
- GitHub Actions [run #3500](https://github.com/justinhblee-prog/shorts/actions/runs/43916192844) succeeded on commit `7c647861481854ed91216dac9d9b69c4ce1d89ba`; `scripts/validate.sh` passed. Unit tests use a controlled thread and mocked provider execution; no live production worker/database deployment validation is claimed.


## BUILD-00273 — Test production worker restart and lease-recovery race
- Add a deterministic concurrent regression where a production worker restarts while an expired production lease is recovered.
- Verify the ambiguous external provider operation is terminalized rather than automatically requeued, the production queue remains paused for manual reconciliation, and the prior process generation cannot mark the replacement worker offline or finish the old job.
- GitHub Actions run [#3504](https://github.com/justinhblee-prog/shorts/actions/runs/43917868295) succeeded on commit `9f118549903b1f252b8c911cd363d96c827568cb`; `scripts/validate.sh` passed. The test uses local SQLite and concurrent threads; no live provider or production worker validation is claimed.


## BUILD-00274 — Fence concurrent provider retries
- Add a concurrent same-job/stage regression using synchronized threads: exactly one provider attempt may start while the external outcome is unresolved; competing attempts receive a conflict.
- Verify a further retry remains blocked until an operator explicitly confirms the prior request was not executed with supporting evidence.
- After that reconciliation, verify a new attempt is permitted with a distinct idempotency key and incremented attempt number.
- GitHub Actions checks for PR #279 both succeeded on commit `443bb057c65b63427f73ad7dbc14b5319daef5f9`; deterministic local SQLite/concurrency tests only. No live provider API validation is claimed.


## BUILD-00275 — Serialize concurrent operator reconciliation
- Added a synchronized two-thread SQLite regression for two operators attempting to reconcile the same ambiguous production job concurrently.
- Verified exactly one reconciliation succeeds, one is rejected after the state transition, exactly one immutable reconciliation/audit event is recorded, and the global production pause remains active.
- GitHub Actions checks succeeded on commit `7661fba934e9889f515b181c6b7ef956bb28c8f6`. This is deterministic local concurrency coverage; no live provider or multi-host production validation is claimed.


## BUILD-00276 — Fence stale worker shutdown writes
- Pass the active worker ID and process-generation token from the SIGTERM handler into the durable queue pause operation.
- Reject shutdown pause writes from an obsolete worker incarnation after a replacement process registers, while always signaling local stop and lease-loss events.
- GitHub Actions checks for PR #281 both succeeded on commit `3000e30c18889d726adc439bf906aa704bc1470e`. This validates deterministic unit/CI coverage only; no live multi-process deployment validation is claimed.


## BUILD-00277 — Verify stale SIGTERM cannot pause a replacement worker
- Add a SQLite-backed regression that registers an old worker generation, registers its replacement, and lets the replacement claim a production job.
- Deliver a delayed shutdown request with the old generation token and verify the local stop signals are still set while the replacement job remains running and the global production queue remains unpaused.
- GitHub Actions validation for PR #282 is pending at the time of this documentation update. The regression uses local SQLite and does not claim live multi-process deployment or provider API validation.


## BUILD-00278 — Verify current-generation shutdown safely pauses active production
- Add a SQLite-backed positive-path test for SIGTERM from the currently registered worker generation while it owns a production job.
- Assert local stop/lost-lease signals, durable global pause, terminalization with lease revocation, worker-pause audit event, and rejection of a late completion attempt.
- GitHub Actions validation for PR #283 is pending. This is deterministic SQLite coverage, not live multi-process deployment or provider API validation.


## BUILD-00279 — Reconcile ambiguous production cancellations
- Include production jobs cancelled while a provider request may be in flight in the ambiguous-production operator queue.
- Permit retry authorization only from the exact cancelled/ambiguous state, requiring operator evidence and note; transition the queue and production run to retry-authorized state while retaining the global pause and immutable audit trail.
- Regression covers discovery, missing-evidence rejection, authorized retry, production-run state, and audit provenance. GitHub Actions validation is pending; no live provider-console or production API verification is claimed.


## BUILD-00280 — Capture cancellation timestamps after acquiring the queue write lock
- Move cancellation timestamp capture inside the SQLite `BEGIN IMMEDIATE` transaction, after the write lock is acquired.
- Prevent lock contention from causing a cancellation's persisted `updated_at` and audit-event timestamp to predate the actual serialized state transition.
- Add a deterministic lock-contention regression that advances the controlled clock while cancellation waits for the write lock and checks both the job timestamp and cancellation event timestamp.
- Validation is pending GitHub Actions. This is local SQLite concurrency coverage only; no production database or provider validation is claimed.


## BUILD-00281 — Reconcile production jobs fenced by a queue pause
- Treat every in-flight production job revoked by a global production pause as an ambiguous external outcome instead of a generic `worker_paused` terminal failure.
- Expose these jobs through `ambiguous_production_jobs()` and permit only evidence-gated operator reconciliation; the production queue remains paused after authorization.
- Extend the pause regression to verify lease fencing, ambiguity discovery, missing-evidence rejection, authorized retry transition, and audit provenance.
- Validation pending GitHub Actions. SQLite-backed deterministic tests only; no production provider verification is claimed.



## BUILD-00282 — Capture reconciliation timestamps after acquiring the queue write lock
- Move the production retry-reconciliation timestamp capture inside the `BEGIN IMMEDIATE` transaction, immediately after SQLite grants the write lock.
- Prevent lock contention from making the retry availability time, job update time, reconciliation record, and audit event predate the serialized operator decision.
- Add a deterministic SQLite lock-contention regression that advances the controlled clock while reconciliation waits and checks all persisted timestamps.
- GitHub Actions [run #43924694183](https://github.com/justinhblee-prog/shorts/actions/runs/43924694183) passed on the PR head; deterministic local SQLite concurrency coverage only, with no production database or provider-console validation claimed.


## BUILD-00283 — Quarantine active production when a worker generation is replaced
- During worker registration, detect production jobs still running under the reused worker ID before rotating its process-generation token.
- If an in-flight production lease exists, persist the global production pause and terminalize all running production leases as ambiguous before the replacement process becomes active; the old process cannot continue through a valid queue lease and the new process cannot start another production job until operator review.
- Add a SQLite regression for re-registration during an active production lease, covering lease revocation, ambiguous-job discovery, stale-heartbeat rejection, replacement-worker claim blocking, and preservation of the new online generation.
- GitHub Actions [run #43930282954](https://github.com/justinhblee-prog/shorts/actions/runs/43930282954) passed: `scripts/validate.sh` completed and all 642 backend tests passed. This is deterministic CI/SQLite coverage only; no live multi-process/provider verification is claimed.


## BUILD-00284 — Keep production-pause audit timestamps on the serialized transition
- Reuse the timestamp captured after the caller acquired SQLite's immediate write lock for each worker-pause job audit event.
- Avoid independently sampling the wall clock inside the audit helper, which could make the immutable event timestamp disagree with the queue-control event and job transition timestamp.
- Add a deterministic regression that supplies a controlled transition timestamp and checks the job, job-event, and worker-control-event records all persist the same value.
- Validation pending GitHub Actions; this change adds deterministic SQLite coverage only and does not claim production multi-host validation.


## BUILD-00285 — Report every production job terminalized during lease recovery
- When an expired production lease triggers the global pause, count the other still-running production jobs that the same transaction terminalizes.
- Keep the recovery API's terminal count aligned with the durable state changes instead of reporting only the expired lease rows.
- Add a regression with one expired and one still-valid production lease; recovery must report both terminalized jobs.
- GitHub Actions validation pending. Deterministic SQLite coverage only; no live provider execution is claimed.


## BUILD-00286 — Align expired-lease audit events with the recovery transaction timestamp
- The recovery transaction already captures one timestamp after acquiring its SQLite write lock, but lease-expiry job events independently sampled the wall clock.
- Pass the transaction timestamp into the immutable lease-expiry event so the event and job state describe the same serialized decision.
- Add a deterministic regression that advances the mocked clock between the recovery decision and event creation.
- GitHub Actions validation pending; no live multi-host validation is claimed.


## BUILD-00287 — Align operator-reconciliation job events with the locked decision timestamp
- Operator retry reconciliation already captures its decision timestamp after acquiring SQLite's immediate write lock and persists it to the job and reconciliation ledger.
- Pass that same timestamp to the job-event audit writer instead of sampling the clock a second time.
- Add a deterministic regression checking all three records (job, reconciliation ledger, job event) share the same timestamp.
- GitHub Actions validation pending; deterministic SQLite coverage only.


## BUILD-00287 — Align cancellation audit timestamps
- Reuse the timestamp captured after the SQLite write lock for the cancellation job event instead of sampling the clock independently.
- Keep the job state transition and its audit event on the same serialized decision time.
- Add a deterministic regression with a controlled clock that advances after the transition timestamp is captured.
- GitHub Actions validation pending; no live production provider validation is claimed.


## BUILD-00288 — Reuse transition timestamps across worker lifecycle events
- Pass the timestamp already captured under the SQLite write lock into claim, heartbeat, finish, and fail job-event records.
- Prevent event helper clock reads from drifting away from the state transition that the event describes.
- Add deterministic controlled-clock coverage for finish and fail transitions.
- GitHub Actions validation pending; deterministic SQLite tests only, no live distributed-worker validation is claimed.


## Release readiness inventory — 2026-11-17

See [docs/RELEASE_READINESS.md](RELEASE_READINESS.md) for the evidence-based remaining-work plan, phase exit criteria, and launch checklist.

- The current repository does not define a finite total engineering acceptance backlog; therefore no honest overall project completion percentage can yet be calculated from BUILD numbers or open PR counts.
- The explicit Operator Runbook launch checklist has 8 gates. Gate 1 (`scripts/validate.sh` on Python 3.11+) is verified by successful GitHub Actions on PR #308 head `2b70602d274a4ed583516a22d092728dee1a257d` (run #43993556051). The remaining 7 gates require Docker/deployment, real provider/media, YouTube, financial, security/operations, and cohort/ROI evidence.
- Launch-gate progress: **1/8 (12.5%)**. This is not an overall product completion percentage.
- PRs #288–#295 and #297–#308 remain Draft and unmerged; PR #296 is closed as a superseded duplicate. Preserve the no-merge/no-main-push constraint.
- BUILD-00289 (PR #294), BUILD-00290 (PR #295), and BUILD-00291 (PR #297) have successful exact-head GitHub Actions validation.
- BUILD-00292 (PR #298) passed CI on exact head `1f47019894854ea87565f00eb1c67fd64dbfbfeb`.
- BUILD-00293 (PR #299) passed CI on exact head `724d4f78425577debc74a7990cf4d34133162390`.
- BUILD-00294 (PR #300) passed CI on exact head `00a55e1ae52a102a7eddfa52d3bc65c0b58aa8db` (run #43990440580).
- BUILD-00295 (PR #301) passed CI on exact head `62e5211c51305b71102c52f94b4525ca47b38407` (run #43990907642).
- BUILD-00296 (PR #302) passed CI on latest docs-inclusive head `22af5871853f7f124af9c92b37bf9887d3126a3a` (run #43991125723).
- BUILD-00297 (PR #303) passed CI on latest docs-inclusive head `5db4bd5ba8d307e9cd7c72aab5b3afd09dc1eedd` (run #43991573385).
- BUILD-00298 (PR #304) passed CI on latest docs-inclusive head `29759c56e2d05f8cf1226b55101dc612776214db` (run #43992018437; 660 backend tests).
- BUILD-00299 (PR #305) passed CI on latest docs-inclusive head `705e897582d0592174719bc4bcff66051c4cc58d` (run #43992365077).
- BUILD-00300 (PR #306) passed CI on latest docs-inclusive head `d0e37b075d2efa46d0a0366642f75ce824238d7d` (run #43992684188; 664 backend tests).
- BUILD-00301 (PR #307) passed CI on latest docs-inclusive head `001237c0cbb20b885557dec3ad2e1ec7c412cb58` (run #43992985705).
- BUILD-00302 (PR #308) passed CI on latest head `2b70602d274a4ed583516a22d092728dee1a257d` (run #43993556051).
- CI and deterministic SQLite coverage must remain separate from live external-service and production validation.


## BUILD-00289 — serialize enqueue audit timestamp after SQLite write-lock acquisition
- Capture the enqueue transition timestamp only after `BEGIN IMMEDIATE` succeeds; use the same value for queue created_at/updated_at and the immutable enqueued job event.
- Add a lock-contention regression proving the clock is not sampled while enqueue waits for the write lock.
- GitHub Actions run 43935191681 passed on exact PR #294 head `12187bbb6b7ad108894405dbbacb84f9456416bf`; `scripts/validate.sh` completed successfully. This is Python 3.11 CI/SQLite coverage, not live multi-host or provider validation.

## BUILD-00290 — serialize production-run creation timestamp
- Acquire SQLite's immediate write lock before sampling the production-run creation timestamp.
- Persist one identical timestamp to production_runs.created_at and updated_at instead of sampling the clock twice before the implicit write transaction.
- Add a lock-contention regression that verifies no clock read occurs while waiting for the lock and both persisted fields use the same decision time.
- Validation pending GitHub Actions; local SQLite regression is not live deployment validation.


## BUILD-00291 — append-only queue and worker-control audit events

- Added SQLite update/delete rejection triggers for `job_events` and `worker_control_events`.
- Added regression coverage that checks `sqlite3.IntegrityError` for mutation and deletion attempts on both audit tables.
- This protects against accidental/application-level mutation, not privileged schema or database-file modification.
- GitHub Actions Backend tests run #43984822638 passed on exact PR #297 head `3f0d4e534b16743c2b650b5f9ac2dc5e92fc678a`. Local SQLite/CI only; no production tamper-proof storage is claimed.


## BUILD-00291 — append-only queue and worker-control audit events
- SQLite triggers reject UPDATE and DELETE operations against `job_events` and `worker_control_events`.
- Regression tests assert SQLite integrity errors for mutation/deletion attempts against both audit tables.
- Missing-queue-row guard tests explicitly remove the trigger before simulating out-of-band deletion; normal operation retains append-only protection.
- GitHub Actions Backend tests run #43984822638 passed on exact PR #297 head `3f0d4e534b16743c2b650b5f9ac2dc5e92fc678a`.
- This is database-local protection, not tamper-proof storage against privileged schema/database-file modification.


## BUILD-00292 — capture schedule activation timestamp after SQLite write lock

- Move the `set_active` timestamp read inside `BEGIN IMMEDIATE`, after SQLite grants the write lock.
- Add a deterministic lock-contention regression proving no activation timestamp is sampled while waiting for the lock and that the committed row uses the post-lock timestamp.
- GitHub Actions passed on exact PR #298 head `1f47019894854ea87565f00eb1c67fd64dbfbfeb`; deterministic SQLite lock-contention coverage only.


## BUILD-00293 — scheduler lease timestamps after SQLite write lock

- Move implicit clock sampling in scheduler lease acquisition and renewal inside `BEGIN IMMEDIATE`.
- Preserve explicit caller-supplied `now` semantics for deterministic scheduling and tests.
- Add lock-contention regressions for both acquire and renew, asserting no clock read while blocked and verifying persisted expiry/update timestamps.
- GitHub Actions passed on exact PR #299 head `724d4f78425577debc74a7990cf4d34133162390`; deterministic SQLite lock-contention coverage only.


## BUILD-00294 — dispatch reservation clock after SQLite write lock

- Move implicit `dispatch_due` clock sampling inside `BEGIN IMMEDIATE`.
- Validate the scheduler fencing lease in the same write transaction as due-occurrence reservation, closing the pre-lock lease-check race.
- Add a lock-contention regression that verifies the clock is not sampled while blocked and that outbox/schedule timestamps use the post-lock time.
- GitHub Actions run #43990440580 passed on exact PR #300 head `2184c13ac56854075145ce9ad39572cc1ff6004f`; deterministic SQLite lock-contention coverage only.


## BUILD-00295 — serialize scheduler dispatch completion timestamp
- Sample the dispatch-completion clock only after acquiring SQLite's `BEGIN IMMEDIATE` lock, after the idempotent queue enqueue has returned.
- Reuse the same completion timestamp for scheduler fencing-lease validation, outbox `dispatched_at`, and schedule `last_enqueued_at`/`updated_at`.
- Add a synchronized lock-contention regression: pause after queue acceptance, acquire a competing SQLite write lock, release enqueue, and verify the completion clock is not sampled until the lock is granted.
- GitHub Actions run #43990763068 passed on exact PR #301 head `17cff30eae5e05893eb03e7db04638c32bbdbcea`. Deterministic SQLite/CI coverage only; no deployed scheduler or multi-host validation is claimed.


## BUILD-00296 — serialize schedule creation timestamp
- Acquire SQLite's `BEGIN IMMEDIATE` write lock before sampling the schedule creation timestamp.
- Use one post-lock timestamp for `created_at`, `updated_at`, and the default `next_run_at` when `start_at` is omitted; preserve explicitly supplied timezone-aware start times.
- Add a lock-contention regression that verifies the default clock is not sampled while creation waits for the write lock and all three persisted timestamps match.
- GitHub Actions run #43991125723 passed on latest docs-inclusive PR #302 head `22af5871853f7f124af9c92b37bf9887d3126a3a`. Deterministic SQLite coverage only; no deployed scheduler or multi-host validation is claimed.


## BUILD-00297 — serialize scheduler retry backoff after write lock
- Compute a failed dispatch's retry deadline from the failure timestamp captured after acquiring SQLite's `BEGIN IMMEDIATE`, rather than reusing the dispatch-loop start time.
- Validate the scheduler fencing lease in the same transaction before persisting retry/dead-letter state.
- Preserve explicit caller-supplied `now` semantics for deterministic invocations.
- Add a lock-contention regression with a delayed queue failure; verify the retry backoff starts from the post-lock failure timestamp.
- GitHub Actions run #43991377065 passed on latest PR #303 code head `76655c1269863ce7a5b364d1c18af0017e022c0c`. Deterministic SQLite coverage only; no deployed or multi-host scheduler validation is claimed.


## BUILD-00298 — serialize production provider-attempt lifecycle timestamps
- Move provider-attempt start, response completion, adoption, unknown-outcome and operator-reconciliation timestamps inside SQLite's `BEGIN IMMEDIATE`.
- Reuse the captured timestamp for worker-lease validation and its associated provider-attempt transition.
- Make production stage and artifact writes acquire the immediate write lock before sampling timestamps, including calls without an optional worker token.
- Add lock-contention regressions for provider-attempt start, stage updates and artifact creation.
- GitHub Actions run #43991836273 passed on exact PR #304 code head `a71ab730c3e6cb03bcc3dd58830cbdf50f2a9815` (660 backend tests). Deterministic SQLite coverage only; live provider/deployed worker validation is not claimed.


## BUILD-00299 — serialize YouTube metrics collector lease clocks
- Sample implicit metrics collector acquire/renew times only after acquiring SQLite's `BEGIN IMMEDIATE` lock.
- Reuse the same post-lock time for lease expiry validation and persisted lease `updated_at`.
- Move metrics collection-state and video-snapshot timestamps inside their write transactions, always acquiring the immediate lock even without optional lease arguments.
- Add lock-contention regressions for acquire, renew, collection-state and snapshot writes.
- GitHub Actions run #43992153984 passed on exact PR #305 code head `6011e49cab4b09de103eeb187f52ff0177291f0c`. Deterministic SQLite coverage only; live YouTube API and deployed collector validation are not claimed.


## BUILD-00300 — serialize TikTok publication timestamps
- Acquire SQLite's `BEGIN IMMEDIATE` before sampling the TikTok pre-remote failure timestamp.
- Reuse one transaction timestamp for consent/start, initialization, active status transitions and their audit events.
- Reuse one post-lock timestamp for operator reconciliation age validation, final state and event records.
- Add a lock-contention regression for the pre-remote failure transition.
- GitHub Actions run #43992497146 passed on exact PR #306 code head `3980ce2afb996d25823e0a6532e7317b23f4e99a` (664 backend tests). Deterministic SQLite coverage only; live TikTok API/deployed publisher validation is not claimed.


## BUILD-00301 — serialize YouTube upload state and audit timestamps
- Reuse one timestamp for upload reservation and its audit event, and one for successful upload finalization and its event.
- Acquire SQLite's `BEGIN IMMEDIATE` lock before sampling upload-touch timestamps.
- Reuse one post-lock timestamp for operator reconciliation state and event records.
- Add a lock-contention regression for upload-touch writes.
- GitHub Actions run #43992793568 passed on exact PR #307 code head `0431b7598dbd751b45d555b607fc540b11d67182`. Deterministic SQLite coverage only; live YouTube API/deployed upload validation is not claimed.


## BUILD-00302 — serialize OAuth state and refresh lease clocks
- Move YouTube and TikTok OAuth state creation/consumption clock reads inside SQLite's `BEGIN IMMEDIATE` write transactions.
- Move TikTok refresh-lease acquisition time sampling inside its write transaction.
- Add lock-contention regressions for OAuth state creation/consumption and TikTok refresh-lease acquisition.
- GitHub Actions is running on PR #308 code head `220737ee5383531164001befdf938a717411a6f7`; deterministic SQLite/controlled-clock coverage only. Live Google/TikTok OAuth provider validation is not claimed.


## BUILD-00302 — serialize OAuth state and refresh lease clocks
- Move YouTube and TikTok OAuth state creation/consumption clock reads inside SQLite's `BEGIN IMMEDIATE` write transactions.
- Move TikTok refresh-lease acquisition time sampling inside its write transaction.
- Add lock-contention regressions for OAuth state creation/consumption and TikTok refresh-lease acquisition.
- GitHub Actions run #43993556051 passed on latest PR #308 head `2b70602d274a4ed583516a22d092728dee1a257d`. Deterministic SQLite/controlled-clock coverage only; live Google/TikTok OAuth provider validation is not claimed.



## BUILD-00303 — make review decision and policy evidence audit records append-only
- Add SQLite UPDATE/DELETE rejection triggers to `review_decisions` and `policy_evidence_events`.
- Preserve ordinary INSERT behavior so review decisions and policy attestations continue to append.
- Add regression coverage proving mutation and deletion fail with `sqlite3.IntegrityError` and both records remain present.
- Scope limitation: this is application/database-trigger protection against accidental mutation, not tamper-proof storage against privileged schema or database-file modification.
- GitHub Actions run #43995020465 passed on implementation head `daa75c737b9d5b5b63b12b110dd65bdeb60ccfd0` (668 backend tests). The later documentation-only checkpoint will receive its own exact-head CI run.


## BUILD-00304 — prevent retry authorization after late production completion
- Harden `JobQueue.reconcile_production_retry`: if the production run is already `approved` or `uploaded`, reject the retry authorization rather than silently leaving that run unchanged while making its queue job retryable.
- When a production-run row exists and is eligible, require the same transaction to update exactly that row before recording reconciliation events.
- Preserve the existing supported case where the production_runs table or the individual run row does not yet exist.
- Add a regression simulating a late authoritative upload completion after an ambiguous queue cancellation; verify the queue remains cancelled, the production run remains uploaded, the global pause remains, and no retry audit is written.
- GitHub Actions run #44014933856 passed on exact PR #310 implementation head `485f9d8e05e323323d38d73edf52e833b82c5f1b` (669 backend tests).
