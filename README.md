# NEXUS STUDIO PRO

Revenue-oriented automation platform for researching, producing, reviewing and publishing short-form video content across brands and global markets.

## Backend foundation

BUILD-00001 implements the first durable queue and Worker Lease foundation. See [backend/README.md](backend/README.md).

- FastAPI: `backend/app.py`
- SQLite queue and lease fencing: `backend/queue_store.py`
- Tests: `backend/tests/`

Generated content enters human review before any public publishing action. Estimated revenue and performance must never be represented as measured results.
