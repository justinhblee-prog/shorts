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
