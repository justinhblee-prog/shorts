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
