# NEXUS STUDIO PRO — Operator Runbook

Version: 0.2  
Scope: single-host Docker deployment and supervised operation.

## 1. Configuration

Copy `.env.example` to `.env`. Never commit the real file.

Required for protected operations:
- `NEXUS_REVIEW_TOKEN`: long, random operator token.

Required for end-to-end AI production:
- `SCRIPT_PROVIDER_URL`, `SCRIPT_PROVIDER_TOKEN`
- `VOICE_PROVIDER_URL`, `VOICE_PROVIDER_TOKEN`
- `RENDER_PROVIDER_URL`, `RENDER_PROVIDER_TOKEN`

The provider adapters expect JSON-over-HTTPS request/response contracts documented in `backend/README.md`. A configured URL is not proof that a provider is compatible; verify each adapter against the actual vendor contract and a real generation.

Required for artifact staging:
- `RENDER_ARTIFACT_HOSTS`: comma-separated exact hostnames that the renderer uses for downloadable MP4 artifacts.
- `NEXUS_MEDIA_DIR`: shared staging directory; Docker Compose sets this to `/app/data/media`.
- `NEXUS_MAX_MEDIA_BYTES`: upload/download size cap, default 256 MiB.

Required for YouTube:
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `YOUTUBE_DATA_API_KEY`

Never put credentials into source files, UI code, query strings or commit messages.

## 2. Start services

At repository root:

```bash
docker compose build
docker compose up -d
docker compose ps
```

Open `http://localhost:8502/`. The API, worker and scheduler use the same persistent SQLite volume. Run exactly one scheduler instance. The dashboard's token is held in browser memory only; refreshing the browser clears it.

## 3. Production lifecycle

1. In the Studio section, choose an active brand, market and language, then submit a topic.
2. The durable queue dispatches `short_video_production` to the worker.
3. The worker calls script, voice and renderer providers. Missing credentials or malformed provider responses fail the stage; no placeholder artifact is accepted.
4. The production enters `review_pending`. Open the remote renderer artifact link and inspect the real output.
5. Use **미디어 스테이징** or the approved-upload queue. Staging reads the saved artifact URL from the production record; the operator cannot supply an arbitrary URL.
6. Approve or reject the production. Rejection and revision require a reason.
7. In **승인 완료 · 비공개 업로드**, explicitly choose **비공개 업로드**. The YouTube API request sets `privacyStatus=private`.
8. Confirm the returned YouTube video ID and inspect the upload record.

The UI does not provide a public-publish action. Human approval is mandatory.

## 4. Artifact staging security

The stager:
- requires HTTPS;
- accepts only exact allowlisted hostnames;
- rejects URL credentials, non-443 ports and redirects;
- resolves and rejects non-public IP addresses, then connects to a pinned public IP while retaining TLS hostname verification;
- limits streamed bytes and validates MP4 MIME type and `ftyp` signature;
- writes to a temporary file and atomically moves the completed file into the media directory.

CDN compatibility is not universal. Add only the exact trusted hostnames required by your renderer. If the vendor uses redirects or non-MP4 output, implement and validate a provider-specific secure adapter rather than disabling these checks.

## 5. Trend and competitor intelligence

- Google News RSS supplies news headlines and source URLs, not search volume or YouTube view velocity.
- Hacker News scores/comments are source-provided signals, not proof of market demand.
- YouTube Data API public counters are point-in-time observations. Hidden subscriber counts remain unavailable.
- YouTube Data API search calls consume quota; avoid frequent broad searches.

## 6. Financial controls

- Record actual transactions with a unique source reference.
- Keep YouTube ad revenue, affiliate income, sponsorship income and costs distinct.
- Use the correct ISO currency code. Reports are currency-filtered; do not add currencies together.
- Profitability scoring is a scenario estimate based on operator-supplied assumptions. It is not an earnings forecast or guarantee.
- Performance insights compare stored counter snapshots; they are not causal attribution, retention analytics or real-time view velocity.

## 7. Recovery and operations

- Inspect queue state and worker heartbeats from the dashboard.
- Worker leases are fenced; stale workers cannot complete a job after losing ownership.
- Scheduler dispatch uses deterministic idempotency keys. Run one scheduler process until distributed leadership is implemented.
- Back up the persistent SQLite volume and test restoration before real operation.
- Do not scale multiple API/worker/scheduler instances on shared SQLite as if it were a production distributed database.

## 8. Validation checklist before launch

- [ ] Complete `./scripts/validate.sh` successfully in a real Python 3.11+ environment.
- [ ] Build and start Docker Compose; confirm all three services stay healthy.
- [ ] Verify each provider's real script, voice and video output, including licensing and costs.
- [ ] Verify renderer CDN host allowlisting and staged MP4 playback.
- [ ] Verify YouTube OAuth scopes and one private test upload on the intended channel.
- [ ] Verify YouTube Analytics and external affiliate/sponsor statements against ledger entries.
- [ ] Configure HTTPS, secret rotation, backups, restore drills, monitoring and alerting.
- [ ] Validate one small content cohort and actual net ROI before scaling.

## 9. Current known blockers

GitHub Actions runs have repeatedly ended before runner allocation with `runner_id=0`, empty runner name and no steps. This is an infrastructure/runner allocation failure, not evidence that tests passed or failed. A rerun has been requested, but no successful test execution has been observed.

Real provider credentials, renderer CDN hostnames, YouTube OAuth and financial integrations are external dependencies. No real revenue outcome is established by the committed source code.
