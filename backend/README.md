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


## Profitability scoring (scenario estimates)

- `POST /api/opportunities/score` accepts low/high view forecasts, RPM assumptions, cost ranges, optional affiliate/sponsor assumptions, monetization eligibility and evidence/fit/feasibility scores.
- `GET /api/opportunities` lists saved scenarios by priority score.
- A non-empty `forecast_source` is required. Results are explicitly labeled `estimate`; they are not actual earnings or guaranteed results. If monetization is not eligible, ad revenue is forced to zero.
- The prioritization score is explainable: margin 35%, ROI 25%, evidence quality 20%, strategic fit 10%, production feasibility 10%.


## BUILD-00005 — short-video production pipeline

The provider-agnostic orchestration layer is in `production_pipeline.py`.
It submits durable `short_video_production` queue jobs and executes three
configured provider stages in order: script, voice generation, and 9:16 video
rendering. Provider URLs and optional bearer tokens are read from the runtime
environment:

- `SCRIPT_PROVIDER_URL`, `SCRIPT_PROVIDER_TOKEN`
- `VOICE_PROVIDER_URL`, `VOICE_PROVIDER_TOKEN`
- `RENDER_PROVIDER_URL`, `RENDER_PROVIDER_TOKEN`

Each provider accepts a JSON POST contract. Script providers must return a
non-empty `script`; voice providers must return an HTTP(S) `audio_url`;
renderers must return an HTTP(S) `video_url`. Provider-specific adapters can
map vendor APIs to this contract without coupling the core pipeline to one
vendor. Missing configuration or malformed output fails closed; no placeholder
audio/video or fabricated artifact URL is created.

API:
- `POST /api/production/jobs` — create a durable job; body: `brand`, `region`,
  `language`, `topic`, optional `idempotency_key`.
- Claim the job with `POST /api/jobs/claim`.
- `POST /api/production/jobs/{id}/execute` — execute only with the current
  `worker_id` and `lease_token`.
- `GET /api/production/jobs/{id}` — inspect stages and artifacts.
- `python worker.py` — run the long-lived worker. It claims only `short_video_production` jobs, renews its lease while provider calls run, and finalizes the queue into `review_pending` after successful rendering.

A completed render transitions the queue job to `review_pending`. This is not
a publish operation. Public publishing remains outside this pipeline and must
require explicit human approval. Provider contracts have mocked unit tests;
live provider compatibility, actual generation, artifact download/playback,
and render quality have not been validated.


## BUILD-00006 — ten-brand operations

`brand_operations.py` seeds and persists the ten operating brands. Each profile
defines its vertical, positioning, audience, tone, supported markets/languages,
risk level and editorial review rules. Defaults are inserted only when missing,
so operator activation settings survive restarts.

API:
- `GET /api/brands` — list all brands.
- `GET /api/brands?active_only=true` — list active brands only.
- `GET /api/brands/{slug}` — inspect a brand profile.
- `PUT /api/brands/{slug}/activation` with `{"active":false}` — pause or
  reactivate a brand.

Production job creation accepts a registered active brand name or slug and
rejects unsupported region/language combinations. Initial supported regions
are KR, US, JP and GB; supported languages are Korean, English and Japanese.

## BUILD-00007 — human review

Configure a strong `NEXUS_REVIEW_TOKEN` secret in the API environment. Review endpoints require it in the `X-Review-Token` header and fail closed if unset.

- `GET /api/review/pending`
- `POST /api/review/{job_id}/approve`
- `POST /api/review/{job_id}/reject`
- `POST /api/review/{job_id}/request-revision`
- `GET /api/review/{job_id}/history`

Request body: `{"reviewer_id":"operator-1","comment":"Optional approval note"}`. Rejection and revision requests require a comment. Decisions record the reviewed artifact snapshot and are append-only; a decision cannot be overwritten. Approval does not trigger upload or public publishing. The current reviewer ID is asserted by the caller; integrate a real identity provider and role-based authorization before multi-user production deployment.

## BUILD-00008 — YouTube private publishing and counters

Configure `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` as runtime secrets. The refresh token must be granted `youtube.upload` and `youtube.readonly` scopes. Never commit credentials or token files.

The upload endpoint requires the configured `NEXUS_REVIEW_TOKEN` in `X-Review-Token` and a job with a recorded `approved` human decision:
- `POST /api/youtube/upload/{job_id}`
- `GET /api/youtube/uploads/{job_id}`
- `POST /api/youtube/videos/{video_id}/refresh-metrics`

Upload body includes a server-local `media_path`, title, description, tags and category ID. The API forces `privacyStatus=private`; there is no public/unlisted override. The server must already have the rendered file at that local path. Current render providers return artifact URLs, so downloading/staging remote artifacts into trusted local storage is a separate deployment integration and is not silently performed by this endpoint.

Uploads use the Google API client resumable media upload interface. The upload record and source-provided view/like/comment counters are persisted. A missing first metrics response does not invalidate a confirmed upload. Data API counters are not revenue; estimated or actual monetization revenue is handled separately in BUILD-00009.

OAuth credentials are supplied through environment secrets; an interactive OAuth consent UI/token provisioning flow is not included. The initial adapter supports one authenticated YouTube channel per runtime. Mocked tests are committed; real OAuth, upload quota, media processing and live metrics have not been validated.

## BUILD-00009 — financial ledger

Financial records are source-referenced inputs, not inferred earnings. APIs require `X-Review-Token`:
- POST `/api/finance/ledger` — record one revenue/cost item.
- GET `/api/finance/report?brand=...&from_date=...&to_date=...&currency=USD` — separate revenue/cost totals, net and ROI.

Use entry types `youtube_ads`, `affiliate`, `sponsor`, `production_cost`, `platform_fee`, `other_cost`. Every entry needs a source type and stable source reference. The same source/type reference cannot be double-counted. Reports are one currency at a time; no FX conversion or automatic revenue import is implemented.

## BUILD-00010 — performance insights

GET `/api/performance/insights?brand=...` requires `X-Review-Token`. It reports brand-level video snapshot differences and recorded ledger totals. It does not estimate earnings from views or infer trends from a single snapshot. Recommendations are rule-based and include their evidence basis. YouTube retention/watch-time, controlled experiments and autonomous strategy updates are not implemented.
