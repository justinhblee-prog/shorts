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
