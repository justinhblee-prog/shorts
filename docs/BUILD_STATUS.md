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
- Active resumable uploads refresh their local activity timestamp after each completed chunk. A still-`uploading` record becomes eligible for manual reconciliation only after `NEXUS_UPLOAD_STALE_SECONDS` (default 900 seconds; minimum 60 seconds).
- Added authenticated `POST /api/youtube/uploads/{job_id}/reconcile`. An operator must explicitly confirm the outcome, provide a YouTube video ID if uploaded, and record a note.
- If the operator verifies a matching private video, the record is finalized against that video ID. If the operator verifies no remote upload exists, the record becomes retryable. No automatic remote retry occurs while the outcome is ambiguous.
- Dashboard approved-upload queue distinguishes active uploads from stale/uncertain uploads and exposes the reconciliation action only when eligible.
- Added unit tests for uncertain timeout, duplicate-retry blocking, both reconciliation outcomes, required evidence note, conflicting decisions and premature reconciliation rejection.
- **Validation status:** source and tests are committed; they have not executed because GitHub Actions runner allocation has repeatedly failed before steps start. No live YouTube upload was performed.
