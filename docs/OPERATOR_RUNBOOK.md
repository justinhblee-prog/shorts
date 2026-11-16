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

Open `http://localhost:8502/`. The API, worker and scheduler use the same persistent SQLite volume. The scheduler uses a shared-database leader lease; multiple instances may run safely, with one active dispatcher at a time. The dashboard's token is held in browser memory only; refreshing the browser clears it.

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
- Performance insights combine public counter snapshots with channel-authorized YouTube Analytics reports, including engaged views, average view duration, average view percentage and audience-retention curves. Data is delayed and observational; it is not real-time causal attribution. Recommendation score weighting remains disabled.

## 7. Recovery and operations

- Inspect queue state, worker heartbeats, and production pause state from **운영 관제 · 수익 분석 → 예약·작업 현황**.
- If production is paused, inspect the displayed pause reason and audit history. Before resuming, verify the remote provider's job history, generated artifacts, and billing/usage state. Enter the operator ID and a non-empty investigation note, then use **검증 후 생산 재개**. The resume action is confirmed in the UI and permanently recorded in `worker_control_events`.
- The authenticated control API is `GET /api/queue/control`, `POST /api/queue/pause`, and `POST /api/queue/resume`; all require `X-Review-Token`. Pause/resume request bodies contain `operator_id` and `note`. Resume returns HTTP 409 when the queue is not paused.
- When production is paused, the scheduler still reserves due occurrences in its durable outbox but does not enqueue production jobs. Those pending occurrences are replayed idempotently after an operator resumes production. If a schedule is deactivated before a pending occurrence is dispatched, that outbox item is marked cancelled and will not be replayed if the schedule is later reactivated. Scheduler logs include actionable exception details and an explicit paused-dispatch warning.
- The production worker heartbeats active job leases every 10 seconds by default (configurable with `NEXUS_HEARTBEAT_SECONDS`, capped at one-third of the lease). This reduces the delay before a worker detects an operator pause or lost lease. In-flight provider HTTP requests still run until their configured timeout; the stop signal prevents the worker from starting the next stage once the request returns. Worker presence is refreshed on every idle/paused polling cycle, not only during a leased job. The API reports workers as offline when their last heartbeat exceeds the queue lease window (minimum 30 seconds), so dead worker records do not remain falsely online.
- Worker leases are fenced; stale workers cannot complete a job after losing ownership.
- Scheduler dispatch uses deterministic idempotency keys. Run one scheduler process until distributed leadership is implemented.
- Back up the persistent SQLite volume and test restoration before real operation.
- Do not scale multiple API/worker/scheduler instances on shared SQLite as if it were a production distributed database.

## 8. Validation checklist before launch

- [ ] Complete `sh scripts/validate.sh` successfully in a real Python 3.11+ environment.
- [ ] Build and start Docker Compose; confirm all three services stay healthy.
- [ ] Verify each provider's real script, voice and video output, including licensing and costs.
- [ ] Verify renderer CDN host allowlisting and staged MP4 playback.
- [ ] Verify YouTube OAuth scopes and one private test upload on the intended channel.
- [ ] Verify YouTube Analytics and external affiliate/sponsor statements against ledger entries.
- [ ] Configure HTTPS, secret rotation, backups, restore drills, monitoring and alerting.
- [ ] Validate one small content cohort and actual net ROI before scaling.

## 9. Current known blockers

- Latest fail-closed recovery branch validation: [GitHub Actions run 43667201896](https://github.com/justinhblee-prog/shorts/actions/runs/43667201896), **121 tests passed**.
- Real provider credentials, renderer CDN hostnames, YouTube OAuth and financial integrations remain external dependencies. CI does not establish live provider compatibility, actual media generation, private YouTube upload, revenue ingestion or deployment readiness.
- The application still uses a single-host SQLite architecture; multi-host distributed worker/scheduler operation is not established.

### Review queue recovery

The worker reconciles completed queue jobs before claiming new work. The authenticated pending-review API also performs this reconciliation. If a process stops after the durable queue enters `review_pending` but before the production record is updated, the next worker poll or pending-review request repairs the production record. The queue status is authoritative; jobs that are not durably `review_pending` are never promoted by this recovery path.
## YouTube upload timeout / ambiguous result recovery

A resumable upload can reach YouTube even if the client loses the final response. Do not simply retry an upload that is stuck in `uploading` or marked `reconciliation_required`; this can create duplicate private videos.

1. Wait for the active upload window to expire. A background heartbeat keeps active resumable uploads fresh. The default stale threshold is 900 seconds; configure `NEXUS_UPLOAD_STALE_SECONDS` (minimum 60 seconds) only if your upload sizes and network conditions justify it.
2. Open the intended YouTube channel's YouTube Studio content list and inspect private videos. Compare the intended title, approximate upload time and video ID.
3. In the approved upload queue, choose **업로드 결과 대조**.
4. If the video exists, select `uploaded`, enter its YouTube video ID and record the verification note. The local upload ledger is finalized without creating another video.
5. If and only if no matching video exists, select `not_uploaded` and record the check. The job becomes eligible for a new private upload attempt.
6. If the result is uncertain, do not reconcile as `not_uploaded`; leave the record blocked and investigate further.

The endpoint requires the operator token, an explicit confirmation flag and a non-empty note. This is a manual reconciliation workflow; the current implementation does not query YouTube Studio to discover an upload whose video ID was never received.

### Upload authorization re-check — 2026-11-15

- YouTube upload now requires the **latest** review decision to be `approved`; an earlier approval does not survive a later revision/rejection decision.
- The upload claim re-checks both `production_runs.status='approved'` and the latest `review_decisions.decision='approved'` under `BEGIN IMMEDIATE` in the same SQLite database transaction that claims the upload. This closes the check-then-claim gap against concurrent review-state changes.
- Regression tests cover a later revision decision and a production record that is no longer approved. Tests are committed but remain unexecuted pending a working GitHub Actions runner.

### Worker lease fencing for production writes — 2026-11-15

- `ProductionStore.stage()` and `ProductionStore.artifact()` accept worker identity plus lease token and validate the live `pipeline_jobs` row under `BEGIN IMMEDIATE` before changing production state or artifact records.
- `ProductionPipeline.execute()` carries the claim's worker ID and token through every stage and artifact write. Lease conflicts are propagated without marking the production run failed, preventing an expired worker from overwriting a replacement worker's state.
- The authenticated API execution route passes its verified worker ID and lease token into the pipeline and uses durable review-handoff reconciliation after queue completion.
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


### Durable production-worker pause — 2026-11-15

- A provider failure, lease conflict, heartbeat/database failure, or unexpected worker exception now persists a short-video production queue pause. Every claim path excludes `short_video_production` jobs while the pause is active, including generic claims and concurrent worker processes.
- The pause reason, affected job ID and timestamp survive worker/container restarts. Docker's `restart: unless-stopped` policy cannot silently resume queue consumption.
- On pause, every currently running `short_video_production` job is fenced and moved to `failed_terminal` with a `worker_paused` event; the matching `production_runs` row is synchronized in the same SQLite transaction. This prevents stale workers from writing after the stop. Queued jobs remain untouched, and unrelated queue job types are not paused. A known retryable provider failure is recorded before the pause and remains `failed_retriable`, but it cannot be dispatched until resume.
- Inspect the durable pause before resuming:

```bash
docker compose exec worker python -c "from queue_store import JobQueue; print(JobQueue('/app/data/nexus.sqlite3').worker_control())"
```

- Resume only after the cause and affected job have been investigated and any ambiguous external side effect has been reconciled:

```bash
docker compose exec worker python -c "from queue_store import JobQueue; print(JobQueue('/app/data/nexus.sqlite3').resume())"
```

- Resume clears only the global worker pause. It does not automatically change a terminal job state or reconcile an uncertain provider result. Confirm the affected job's queue and production records before allowing it to retry.


### Queue idempotency contract — 2026-11-15

- Repeating a submission with the same idempotency key, job type, channel and JSON payload returns the existing job without creating another queue entry.
- Reusing that key with a different job type, channel or payload is rejected with HTTP 409. The original job remains unchanged.
- A client retry must resend the original request body with the original key. Generate a new key only for a genuinely new production request.


### Ambiguous production worker loss — fail-closed recovery

- A short-video production job whose worker lease expires is **not automatically requeued**. The provider may have completed an external side effect even if the worker died before persisting its result.
- Expired production work is moved to `failed_terminal` with `production_lease_expired_ambiguous`; the matching production record is synchronized and the production queue is durably paused.
- A normal worker interruption (Ctrl+C) during provider execution records a non-retriable ambiguous failure, pauses the production queue, and exits. A hard process/host kill is handled by the lease-expiry path on the next claim/recovery.
- Operators must inspect the provider's job history and billing/artifact state before deciding whether to create a new production request. Do not simply retry the same ambiguous job.
- Non-production queue jobs retain their existing lease-expiry retry behavior.


### CI recovery and current validation state — 2026-11-15

- The earlier notes in this runbook stating that tests had not executed describe the pre-runner-allocation period and are superseded by the later successful CI checkpoint.
- Verified GitHub Actions run [43665751844](https://github.com/justinhblee-prog/shorts/actions/runs/43665751844) completed checkout, Python setup, dependency installation and `sh scripts/validate.sh` successfully; the log confirms 113 tests ran.
- CI success is limited to automated backend tests. It does not verify real AI-provider calls, generated media quality, actual YouTube OAuth/upload, real analytics/revenue ingestion, or deployed service behavior.
- Before the next release merge, reconcile the post-PR validation-fix branch with the merged `main` baseline and rerun CI on the resulting release head.


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


## Verified milestone — competitor evidence in profitability ranking (2026-11-15)

- Competitor search results offer **최근 영상 분석** to fetch and persist up to 20 recent public videos per selected channel. Up to 10 channels can be selected for comparison.
- Opportunity scoring evaluates stored recent video titles against the opportunity title using token overlap of at least 25% of topic terms. It reports sample count, topic-matched count, median observed views and up to five examples.
- A transparent sample-based competition adjustment is applied: `min(10, 10 × matched_videos / (selected_channels × 3))` points deducted from the 0–100 priority score. It is separately shown in the score breakdown and does not alter revenue, ROI or margin estimates.
- No sample means no penalty. Results explicitly warn that selected channels/recent videos are not market-wide and cannot establish growth, causal demand or revenue.
- CI exposed a legacy scheduler test adapter without `is_paused()`; missing optional pause inspection now safely defaults to unpaused.
- Verified source HEAD: `eb1a3248ac7429003e3e0f9a024fa02929653a22`. GitHub Actions: https://github.com/justinhblee-prog/shorts/actions/runs/43668719310 — **152 tests passed** and JavaScript syntax validation passed.

**Not verified:** live YouTube data collection requires `YOUTUBE_DATA_API_KEY`. No live competitor coverage, view velocity, market-wide saturation, real AI generation, YouTube upload or actual revenue is claimed.


### Saved opportunity ranking UI — verified 2026-11-15

- The intelligence workspace now fetches and displays the 20 highest-ranked saved opportunity evaluations from `GET /api/opportunities`.
- Each row shows rank, title, priority score, estimated net-profit range, competitor adjustment, sample counts and timestamp. The list refreshes after scoring and via a manual refresh control.
- This is an estimate/ranking view only. It does not represent actual earnings, guaranteed performance or a market-wide competitive assessment.
- Latest source HEAD: `0b32d5ca12aea5c2580264665c4fd3d7cbfe7cf0`. GitHub Actions: https://github.com/justinhblee-prog/shorts/actions/runs/43668889808 — success; **139 tests passed**, including JavaScript syntax validation.


### Multi-instance scheduler leader election — 2026-11-15

- Added a singleton scheduler leader-lease table to the shared SQLite database. A process acquires a unique fencing token; a live lease prevents another process from dispatching, and an expired lease can be taken over after a crash.
- Lease renewal is checked before each outbox dispatch, and the lease token is checked again before marking an outbox item dispatched. A stale scheduler cannot renew or release a newer owner's lease.
- The existing outbox and deterministic queue idempotency key remain the final duplicate-dispatch protection if a process dies after enqueue but before recording the outbox completion.
- Added regression coverage for competing owners, expiry/takeover, stale-owner fencing, invalid lease rejection and successful dispatch under a valid lease.
- GitHub Actions run [43670844206](https://github.com/justinhblee-prog/shorts/actions/runs/43670844206) passed **156 tests** on commit `851551896e1bc1b0416427d3a4d6f5964f05862c`. Python compilation, frontend JavaScript syntax/DOM ID checks and Docker Compose YAML parsing also passed.
- Calendar/DST recurrence rules and multi-host database deployment remain outside the current SQLite baseline.


### Integration preflight interpretation

- Provider URLs are required for script, voice and rendering. Provider bearer tokens are optional and should be configured only when the selected vendor requires them.
- The dashboard distinguishes required missing values from optional token omissions.
- YouTube and TikTok configuration readiness are reported independently. TikTok OAuth readiness is separate from the legacy static-token fallback.
- A green configuration result is not a live connectivity or account-authorization test. Complete a real provider generation and private platform test only after credentials, consent, policy review and cost limits are confirmed.


### BUILD-00031 — readiness preflight correction

- GitHub Actions run [43784004930](https://github.com/justinhblee-prog/shorts/actions/runs/43784004930) passed **326 backend tests** and the full validation script.
- The check validates configuration logic and frontend syntax only; perform real provider, OAuth, media and platform checks separately before operating.

## Latest verified code validation — 2026-11-16

- BUILD-00037 CI run [43788723765](https://github.com/justinhblee-prog/shorts/actions/runs/43788723765): **356 backend tests passed**, with Python compilation, frontend JavaScript syntax/DOM-ID checks and Compose YAML parsing.
- This verifies repository code under controlled tests. It does not replace live credentials, provider calls, platform OAuth consent, actual rendering/upload, production deployment or revenue reconciliation.
- Before enabling production posting, verify YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, a refresh token with youtube.readonly and youtube.upload, YOUTUBE_DATA_API_KEY, provider endpoints and any required bearer tokens. For TikTok, complete developer-app review, OAuth redirect and requested scopes, creator-info verification and private-only publishing checks.
- Run a private/test upload and confirm that the resulting platform video ID is collected by both the Data API and Analytics API; do not change privacy to public until policy and human approval checks pass.


### BUILD-00034 — Shorts engaged-view signal

- YouTube Analytics requests both `views` and `engagedViews`; the latter is the API's core metric for views past the initial seconds.
- The dashboard's engaged-view share is a derived diagnostic (engagedViews divided by views), not a YouTube-published percentage.
- The signal is used for performance context and evaluation only. Recommendation score weighting remains disabled until actual channel data and a controlled evaluation justify a separate change.
- GitHub Actions run [43787047727](https://github.com/justinhblee-prog/shorts/actions/runs/43787047727) passed **339 backend tests**.


## BUILD-00036 — connect YouTube securely

1. In Google Cloud Console, enable YouTube Data API v3 and YouTube Analytics API, configure the OAuth consent screen and create a confidential Web application OAuth client.
2. Register the exact HTTPS redirect URI: `https://YOUR_DOMAIN/api/youtube/oauth/callback`. Set the same value in YOUTUBE_REDIRECT_URI.
3. Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET. Generate YOUTUBE_TOKEN_ENCRYPTION_KEY with `Fernet.generate_key()`; protect this key as a production secret and keep it stable so stored tokens remain decryptable.
4. Remove any legacy YOUTUBE_REFRESH_TOKEN environment value if you intend to use the encrypted dashboard connection. Authenticate to the NEXUS dashboard, choose YouTube 연결, complete Google consent, then authenticate to the dashboard again and verify status.
5. Verify the status includes the required youtube.upload and youtube.readonly scopes. The app also requests yt-analytics.readonly. Reconnect if required scopes are missing.
6. Perform a private test upload and Analytics refresh. Do not publish publicly until review, rights, policy and disclosure gates have been completed.

The OAuth callback is protected by a one-time state stored as a hash and a Secure/HttpOnly/SameSite=Lax cookie. Refresh tokens are encrypted at rest. The status endpoint never returns token values. A static YOUTUBE_REFRESH_TOKEN fallback is supported for legacy deployments but must be removed before using the disconnect action.


### BUILD-00036 validation checkpoint

The encrypted YouTube OAuth flow passed **352 backend tests** in [GitHub Actions run 43788265493](https://github.com/justinhblee-prog/shorts/actions/runs/43788265493). Before using it in production, configure the exact Google Cloud redirect URI and Fernet encryption key, complete a real consent flow, verify stored scopes, and perform a private test upload. CI does not prove live account access.


### BUILD-00037 — verify the connected YouTube account

1. Complete the encrypted YouTube OAuth connection.
2. Authenticate to the dashboard and choose **실계정 연결 테스트**.
3. Confirm the returned channel title/ID is the intended channel and both Data API and Analytics API checks are green.
4. If Data API succeeds but Analytics fails, review the granted read-only scopes and reconnect with consent; do not treat the account as fully Analytics-ready.
5. Perform a private test upload and confirm its platform ID and Analytics report are collected before enabling public publishing.

The verification endpoint is protected by the dashboard review token. It never returns access or refresh tokens. Stored OAuth approval and live API verification are distinct states.


### BUILD-00037 verification test

The live verification endpoint is implemented and covered by automated tests, but no real account was tested during CI. After OAuth consent, authenticate to the dashboard and run **실계정 연결 테스트**. Confirm the intended channel title/ID and both Data API and Analytics API states. Only then proceed to a private test upload.


## 8. Automated backup and restore

- Compose includes a backup service that runs immediately at startup and every 24 hours. It snapshots SQLite through the online backup API, archives the staged media directory, writes a SHA-256 manifest, verifies database integrity and retains 14 days by default.
- Backups are written to the separate `nexus_backups` named volume. This protects against application-level mistakes and container recreation but is not off-host disaster recovery. Copy archives to independent object storage or another host.
- Secrets, OAuth refresh tokens and Fernet encryption keys are intentionally excluded. Keep YOUTUBE_TOKEN_ENCRYPTION_KEY and TIKTOK_TOKEN_ENCRYPTION_KEY in a separate secret manager and preserve them across restore.

Manual backup:

```bash
docker compose run --rm --no-deps backup python backup_restore.py backup --db /app/data/nexus.sqlite3 --media-dir /app/data/media --output /backups --retain-days 14
```

Restore is destructive and requires the explicit `--confirm-restore` flag. Stop all writers first; the script validates archive paths, SHA-256 checksums and SQLite integrity, then creates a pre-restore backup before replacing data:

```bash
docker compose stop api worker scheduler metrics-collector backup
docker compose run --rm --no-deps --entrypoint python backup backup_restore.py restore --archive /backups/ARCHIVE_NAME.tar.gz --db /app/data/nexus.sqlite3 --media-dir /app/data/media --output /backups --confirm-restore
docker compose up -d
```

Do not delete the pre-restore backup until the application, media artifacts, OAuth token decryption and worker queue have been checked.


### BUILD-00038 archive validation limits

Backup and restore enforce a maximum of 100,000 archive entries, a 16 MiB manifest, an 8 GiB SQLite database and 200 GiB total media payload. Restore validates paths, manifest shape, duplicate entries, file inventory, SHA-256 checksums and SQLite integrity before it begins replacing live data. These are safety limits, not a substitute for off-host copies and restore drills.
