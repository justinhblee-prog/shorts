# Handover — NEXUS STUDIO PRO v0.1

## Repository
https://github.com/justinhblee-prog/shorts (private), default branch main.

## Current files
- `backend/queue_store.py`: SQLite queue, worker leases, idempotency, retry, events, cancellation and recovery.
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

## Immediate next task
Resolve GitHub Actions runner allocation, execute tests, fix all failures, and only then close BUILD-00001.
