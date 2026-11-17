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


### BUILD-00038 validation checkpoint

The backup/restore utility and Compose configuration passed **362 backend tests** in [GitHub Actions run 43789308031](https://github.com/justinhblee-prog/shorts/actions/runs/43789308031). This verifies code and configuration, not a running daily backup. After deployment, confirm that an archive appears in the backup volume, copy it off-host, and perform a restore drill in a separate staging environment before relying on it for disaster recovery.


### BUILD-00038 archive validation limits

Backup and restore enforce a maximum of 100,000 archive entries, a 16 MiB manifest, an 8 GiB SQLite database and 200 GiB total media payload. Restore validates paths, manifest shape, duplicate entries, file inventory, SHA-256 checksums and SQLite integrity before it begins replacing live data. These are safety limits, not a substitute for off-host copies and restore drills.


## 9. Operator identities, roles and API limits

- Prefer `NEXUS_REVIEW_CREDENTIALS_JSON` with a unique 32–512 character token for each operator. Store tokens in the server secret manager or protected `.env`; do not send them in chat or commit them.
- Configure `NEXUS_REVIEW_ROLE_MAP_JSON` before granting access. Example:
  `NEXUS_REVIEW_ROLE_MAP_JSON='{"alice":["admin"],"bob":["reviewer"],"carol":["publisher"],"dana":["analyst"]}'`.
- Roles are admin, producer, reviewer, publisher, analyst, operator, finance and worker. A user not present in an explicit role map is denied. If per-operator credentials are enabled without a role map, protected requests fail closed. Wildcard access is retained only for legacy single-token migration mode.
- When individual credentials are configured, the legacy `NEXUS_REVIEW_TOKEN` is no longer accepted. Remove it after all operators have moved to individual tokens.
- Default per-minute limits: 120 overall, 20 auth, 10 publishing, 30 queue control, 60 review and 30 production. Tune the corresponding `NEXUS_API_*_RATE_LIMIT_PER_MINUTE` settings based on measured traffic.
- Leave `NEXUS_TRUSTED_PROXY_CIDRS` blank unless the service is behind a known reverse proxy. If needed, list only exact proxy CIDRs; never trust arbitrary X-Forwarded-For values or use `0.0.0.0/0`.



## Encrypted backup key setup (BUILD-00130)

1. Generate a random key on the server: `python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`.
2. Store it as `NEXUS_BACKUP_ENCRYPTION_KEY` in the protected server environment. Never commit the value or place it inside the backup volume.
3. Set `NEXUS_BACKUP_ENCRYPTION_REQUIRED=true` for production after the key has been securely backed up to an independent secret store. This blocks plaintext backup creation and restore.
4. Run the normal Compose backup service; encrypted files end in `.tar.gz.enc`. Restore uses the same environment key and still requires `--confirm-restore` with all writers stopped.
5. Test a restore in a separate staging environment. Losing or rotating the key without re-encrypting retained archives makes those archives unrecoverable.

Legacy `.tar.gz` archives remain restorable while encryption-required mode is false. The restore process authenticates encrypted data before extracting it or changing live data.


## BUILD-00131 — enable ClamAV media scanning

1. Copy the scanner settings from `.env.example`; keep `NEXUS_MEDIA_SCAN_ENABLED=false` until the updater is healthy.
2. Start the updater profile and the regular stack: `docker compose --profile media-scan up -d`.
3. Confirm the updater is running and has populated the persistent database volume: `docker compose logs -f clamav-updater`, then `docker compose exec api ls -lh /var/lib/clamav`.
4. Confirm the binary is available: `docker compose exec api clamscan --version`.
5. Set `NEXUS_MEDIA_SCAN_ENABLED=true` and recreate the API container. Verify the readiness panel reports the malware scanner configured before allowing production staging.
6. If the signature volume is empty or stale, scanner exit code 2/timeouts fail closed and renderer artifacts are not published. Keep the updater running to refresh signatures.

ClamAV adds image size and signature-volume storage. CI validates the fail-closed integration with stubs only; it does not verify live signatures or actual malware detection. Scanner limits are aligned with `NEXUS_MAX_MEDIA_BYTES`; oversized/incomplete scans are rejected rather than treated as clean. Keep HTTPS host allowlists, byte limits, MP4 validation and human approval in place.


### BUILD-00132 — interpreting YouTube retention insights

- Review `retention_diagnostics.largest_dropoff` to identify the video-time interval with the largest adjacent observed audience-watch-ratio decline. This locates a segment; it does not establish why viewers left.
- Compare `analytics_cohorts.metrics` only when `evidence_status=observed`. The cohort requires at least three videos matched on brand, region, publication age, render duration, format and exact topic-token signature.
- Video-level above/below-median observations are hypotheses for controlled creative tests, not ranking boosts. The API keeps `ranking_score_adjustment=0` until held-out validation supports a change.
- No synthetic or inferred retention metrics are generated when YouTube Analytics reports are missing or ineligible.


### BUILD-00132 validation checkpoint

GitHub Actions run [43794456586](https://github.com/justinhblee-prog/shorts/actions/runs/43794456586) passed **431 backend tests** and the complete validation script. This verifies code paths with synthetic fixtures; it does not prove that a live YouTube channel has enough authorized Analytics reports to populate matched cohorts.


### Scheduled YouTube Analytics collector — BUILD-00133

- Complete the YouTube OAuth connection in the dashboard and confirm the token is stored; the periodic metrics collector now reads the encrypted OAuth token store, the same as manual Analytics refresh.
- `YOUTUBE_ANALYTICS_MIN_AGE_SECONDS` controls the minimum age before a video is refreshed (default 86400 seconds).
- `YOUTUBE_ANALYTICS_LEASE_SECONDS` controls the renewable collector lease (default 900 seconds). The collector renews the lease during long batches and refuses to resurrect an expired lease.
- Check `docker compose logs -f metrics-collector` for `youtube_analytics_collection_completed` or `youtube_analytics_collection_failed`. A successful scheduler cycle with zero due videos is not evidence that Analytics reports were retrieved.
- Confirm actual collection by checking the per-video Analytics timestamp and report status in the dashboard/API. OAuth scopes and channel eligibility can still make individual reports unavailable.


### BUILD-00133 validation checkpoint

GitHub Actions run [43794744350](https://github.com/justinhblee-prog/shorts/actions/runs/43794744350) passed **436 backend tests** and the complete validation script. This does not prove a live channel token is present or that a production Analytics report has been collected.


### BUILD-00134 — monitoring YouTube Analytics collection

- Open **운영 관제 · 수익 분석 → 성과 분석** and review the **YouTube Analytics 자동 수집 상태** panel.
- `succeeded` means the last scheduled cycle completed without per-video failures; `partial` means some reports were collected and some videos failed; `failed` means the batch did not complete successfully; `running` indicates a batch is in progress or a process stopped before writing its final state.
- Compare published videos, with-snapshot, without-snapshot and stale/missing counts. The coverage is based on uploaded video IDs and does not imply a metric value for videos whose report is unavailable.
- Use `docker compose logs -f metrics-collector` for detailed exception classes. The API stores only a bounded error summary, not OAuth tokens or response bodies.
- A successful cycle with zero due videos is a successful scheduler cycle, not proof that a new Analytics report was fetched.


### BUILD-00134 validation checkpoint

GitHub Actions run [43795106625](https://github.com/justinhblee-prog/shorts/actions/runs/43795106625) passed **438 backend tests** and the full validation script. This does not prove a deployed metrics-collector service is running or that live YouTube Analytics reports are available.


### BUILD-00135 — interpreting metrics collection errors

YouTube Analytics malformed report payloads are rejected before metrics are saved. If only the audience-retention report is invalid or unavailable, valid watch-time metrics can still be stored with the retention status marked unavailable. TikTok metrics batches are all-or-nothing: if one row is malformed, duplicated or unrequested, no row from that batch is committed; inspect the collector log and retry after the provider response issue is resolved.


### BUILD-00135 validation checkpoint

GitHub Actions run [43795614217](https://github.com/justinhblee-prog/shorts/actions/runs/43795614217) passed **446 backend tests** and the complete validation script. This verifies parser and transaction behavior using test fixtures, not live YouTube/TikTok API responses.


### BUILD-00136 — external media link behavior

Renderer video links and narration previews appear only when their artifact URLs are absolute HTTPS URLs without embedded credentials. If a URL is malformed or uses another scheme, the dashboard hides the link/preview. This does not replace backend host allowlisting, DNS checks, TLS validation or media-byte inspection.


### BUILD-00136 validation checkpoint

GitHub Actions run [43795822579](https://github.com/justinhblee-prog/shorts/actions/runs/43795822579) passed **447 backend tests** and the full validation script. This does not replace browser-level security tests or backend allowlist/media-byte validation.


### BUILD-00137 — cancellation and worker shutdown

- Cancelling a queued production job updates both queue and production state. Cancellation after review handoff or approval is rejected.
- Cancelling while a provider request may be in flight marks the outcome ambiguous and pauses production. Reconcile provider-side job state before resuming or retrying.
- Graceful worker termination now sets the worker registry state to offline immediately. Hard crashes continue to appear offline after their heartbeat becomes stale.


### BUILD-00137 validation checkpoint

GitHub Actions run [43796187131](https://github.com/justinhblee-prog/shorts/actions/runs/43796187131) passed **451 backend tests** and the full validation script. Verify provider-side state manually before resuming after an ambiguous cancellation.


### BUILD-00138 — collector lease health and deployment

- All three metrics collectors now renew their database lease during long batches and verify ownership before committing results.
- YouTube Data API/TikTok use `NEXUS_METRICS_LEASE_SECONDS` (default 300 seconds); YouTube Analytics uses `YOUTUBE_ANALYTICS_LEASE_SECONDS` (default 900 seconds).
- After deployment, restart the `metrics-collector` service so existing SQLite lease tables gain token columns and the new process uses token-fenced writes.
- If the collector reports lease loss, do not retry or replay a late batch manually; inspect the current lease owner and the last stored snapshot timestamp first. Stale writes are rejected by the database.


### BUILD-00138 validation checkpoint

GitHub Actions run [43797131269](https://github.com/justinhblee-prog/shorts/actions/runs/43797131269) passed **462 backend tests** and the complete validation script. After deployment, restart the collector service and verify token-column migrations before enabling multiple collector instances.


## 8. Production schedule interval limits

- Schedule creation accepts whole-number intervals from **3,600 seconds (1 hour) through 31,536,000 seconds (365 days)**.
- The API rejects booleans, fractional values and numeric strings instead of silently converting them to integers. The persistence layer independently enforces the same contract for internal callers.
- To inspect schedules, use **운영 관제 · 수익 분석 → 예약·작업 현황** and review each schedule's next-run timestamp and active state. Deactivating a schedule cancels undispatched outbox entries; reactivating it does not replay those cancelled occurrences.
- The scheduler is an interval scheduler, not a sub-minute polling service. It does not support one-minute recurring schedules.


### BUILD-00162 — scheduler process configuration

The scheduler reads two environment settings at process startup:

- `NEXUS_SCHEDULER_POLL_SECONDS`: integer from 5 to 300; default 30.
- `NEXUS_SCHEDULER_LEASE_SECONDS`: integer from 15 to 3600; default 90.

Both values must be decimal integer strings. The poll interval must not exceed one-third of the leader lease TTL. Invalid values stop startup with a clear configuration error rather than being silently clamped or coerced. For example, a 90-second lease permits a polling interval of at most 30 seconds.


### BUILD-00163 — schedule controls and outbox limits

Internal schedule-store callers must pass a real boolean to activate/deactivate a schedule. Outbox listing limits are integers from 1–500 for pending items and 1–100 for status summaries; dispatch batch limits are integers from 1–100. The scheduler validates its lease TTL before processing, even when there are no due schedules or pending outbox rows. Invalid values raise a clear `ValueError` rather than being coerced or clamped.


### BUILD-00164 — scheduled dispatch retry behavior

When the durable job queue rejects a scheduled outbox item, the scheduler keeps the item pending and records the error. Automatic retries use exponential backoff: 30 seconds after the first failure, then 60, 120, 240 seconds and so on, capped at one hour. Deferred items remain visible in the outbox status screen but are not sent again until `next_attempt_at`. A successful idempotent enqueue clears the retry timestamp. Existing outbox rows are migrated with a null retry timestamp and remain immediately eligible.


### BUILD-00165 — dead-letter scheduler outbox recovery

Outbox entries are retried with exponential backoff for up to 10 failed attempts. After the tenth failure, the entry moves to `dead_letter`, stops automatic retries, and remains visible through `GET /api/schedules/outbox`. An authorized operator with `schedules.manage` permission can explicitly retry an entry using `POST /api/schedules/outbox/{outbox_id}/retry`. Manual retry resets the attempt counter and retry timestamp but preserves the original schedule occurrence and idempotency key, preventing duplicate queue jobs if an earlier enqueue succeeded before a process failure.


### BUILD-00166 — interpreting scheduler outbox status

`GET /api/schedules/outbox` reports total counts by state plus two distinct pending counters: `pending_ready` means eligible for dispatch now, while `pending_retries` means deferred until a future retry timestamp. Dead-letter entries are ordered first in the limited item list so operators can see records requiring manual action. All status timestamps are evaluated in UTC; test callers may supply an aware clock.


### BUILD-00167 — inactive schedule dead-letter protection

Manual dead-letter recovery is permitted only while the parent schedule is active. If a schedule is deactivated, its dead-letter records remain visible for audit but cannot be requeued. Reactivate the schedule first, then retry the specific outbox item. The active-state check and retry-state reset occur in one SQLite statement to avoid a check-then-update race.


### BUILD-00168 — scheduler outbox dashboard

The schedule operations panel distinguishes pending work ready to dispatch from entries deferred by backoff and dead-letter entries requiring operator action. Dead-letter rows expose a manual retry action after confirmation. The API requires the existing `schedules.manage` permission, and the store rejects retry if the parent schedule is inactive; reactivate the schedule before retrying. The outbox item retains its original idempotency key.


### BUILD-00169 — liveness and readiness probes

`GET /api/health` reports only that the API process is responding. `GET /api/ready` additionally verifies that the durable queue and scheduler stores can serve core reads and returns HTTP 503 when storage is unavailable. Docker Compose uses readiness for its API healthcheck, so worker, scheduler, metrics collector and backup startup gates wait for usable shared storage rather than merely an open HTTP process. The probe does not claim that external AI providers, OAuth accounts, workers or publishing APIs are live.


### Worker runtime limits

The production worker validates these settings before opening its queue:

- `NEXUS_LEASE_SECONDS`: integer 30–3600 (default 300).
- `NEXUS_IDLE_SECONDS`: integer 1–300 (default 3).
- `NEXUS_HEARTBEAT_SECONDS`: integer 5–3600 (default 10); the effective heartbeat is capped at one-third of the lease.

Values must be unsigned decimal strings with no whitespace, signs, decimals or exponent notation. Invalid values stop worker startup instead of being silently coerced or clamped. Keep the heartbeat interval comfortably below the lease to allow transient database delays.


### Worker heartbeat monitoring

The authenticated `GET /api/workers` operations view reports each worker's heartbeat age and the stale threshold used for classification. `online` means the last heartbeat is within the threshold; `stale` means an expected heartbeat has stopped arriving; `offline` is reserved for a worker that completed its graceful shutdown bookkeeping. A stale worker is not automatically restarted by this view. Investigate the host/process and the associated job lease before taking recovery action. Production work with an ambiguous external-provider outcome must not be blindly replayed.


### AI production provider outcome reconciliation — BUILD-00173

A production lease expiry or cancellation during a provider request is ambiguous: the provider may have accepted or completed the request even when NEXUS did not persist the response. These jobs remain terminal and are never automatically replayed.

1. Open the authenticated endpoint `GET /api/production/reconciliation` to list production jobs awaiting investigation.
2. Inspect the provider's request/job history, usage/billing records and artifact history using the provider's own console. Do not infer that a request was rejected from a local timeout alone.
3. Only when the provider evidence confirms that **no external side effect occurred**, call `POST /api/production/jobs/{job_id}/reconcile-retry` with `operator_id`, a stable `evidence_reference` (provider request ID or console record), and a non-empty investigation `note`.
4. The action authorizes exactly one additional attempt by extending the attempt ceiling by one. It does not erase the original attempt count or reconciliation audit.
5. The production queue remains paused. Review every affected job, then use the separate authenticated `POST /api/queue/resume` action with a new operator note before workers can claim production work.
6. If the provider shows that generation completed, do **not** use the retry action. Preserve the remote artifact and escalate for a result-adoption workflow; this release intentionally does not fabricate or auto-import provider output.

The append-only `production_reconciliation_events` ledger records operator, outcome, evidence reference, note, previous/resulting state and timestamp. Database triggers reject update/delete. Access requires `queue.read`, `production.read` or `queue.control` permissions as appropriate. The evidence reference is an operator-supplied pointer, not independent proof validated by NEXUS.


### Provider execution response recovery — BUILD-00174

Provider calls are now journaled before the outbound request. Each stage attempt receives a unique persisted request key, attempt number, and state. The key is passed to the provider payload as `request_idempotency_key`; a provider must explicitly support and honor that field before it can be relied upon for remote deduplication.

- `request_started`: NEXUS committed the attempt before the network call. If the process disappears, assume the remote outcome is unknown.
- `response_received`: the complete JSON response was persisted before the pipeline attempts to create or update the corresponding production artifact. The attempt record is the recovery source if artifact persistence did not happen.
- `outcome_unknown`: a transport/provider exception occurred after dispatch may have begun. Do not issue a replacement request based on a timeout alone.
- Authenticated `GET /api/production/jobs/{job_id}/provider-attempts` exposes the attempt ledger, provider request ID, and stored response to principals with `production.read`.
- A response is bounded to 2 MB and stored as JSON. It may contain signed artifact URLs; protect this endpoint and do not copy response bodies into tickets or public logs.
- The request-start transition is fenced by the current worker lease. Once a request has been dispatched, recording the returned response or an unknown outcome is allowed even if that lease expires; this preserves remote truth without allowing the stale worker to write production artifacts.
- The request key is an advisory payload field only. Until the configured vendor confirms support for idempotency keys and request lookup, operators must use the provider's console/request ID to establish whether a generation completed.

This release journals and exposes the response; it does not automatically adopt a recovered artifact or declare it review-ready. Verify the provider request ID, output URL, ownership/retention and actual media bytes, then use the existing allowlisted staging and quality/review workflow. If the provider offers no lookup mechanism, leave the attempt unresolved and do not regenerate automatically.


### Verified adoption of a recovered provider render — BUILD-00175

Use this only when the provider execution ledger contains a `rendering` attempt in `response_received` state. Do not use it for `request_started` or `outcome_unknown` attempts.

1. Inspect the stored provider request ID and response using the authenticated provider-attempt endpoint. Confirm the provider output is the intended render and that its HTTPS URL belongs to a configured `RENDER_ARTIFACT_HOSTS` host.
2. Call `POST /api/production/jobs/{job_id}/adopt-recovered-render` with the exact `provider_attempt_id`. This action requires `media.manage`.
3. NEXUS downloads the file through the existing HTTPS allowlist, public-IP pinning, redirect rejection, size/signature checks and optional malware scan. It then inspects the staged file bytes with ffprobe.
4. Adoption is rejected unless inspection completed, the file is vertical 9:16 within tolerance, has an audio stream, and is no longer than 180 seconds. The attempt, artifact row, production status and queue transition are committed in one SQLite transaction.
5. A successful adoption changes the production and queue state to `review_pending`, records the SHA-256 fingerprint and provider attempt ID, and emits a `provider_result_recovered` queue event. Repeating the action is rejected; a pre-existing render artifact or an active worker lease also blocks adoption.
6. Before queueing review, NEXUS rebuilds a fresh quality report from the stored script/voice artifacts, provider render metadata and ffprobe inspection. Missing script or voice source artifacts block adoption. The report is stored as the normal `quality_check` artifact, so the existing review approval gate still enforces blockers and requires a reviewer note for warnings.

The result is **not approved or published**. A human must inspect the actual video, rights, claims, captions, audio, platform disclosures and brand fit before normal review approval and publication.

If allowlisting, malware scanning, media inspection or required metadata is unavailable, do not bypass the gate. Fix the configuration or leave the provider response preserved for later investigation. The recovery endpoint does not support arbitrary URLs supplied by the operator; it only uses the URL in the stored provider response.


### Review workspace provenance for recovered provider results — BUILD-00176

The pending-review card labels any video artifact carrying `recovered_from_provider_attempt`. It displays the provider attempt ID, staged file SHA-256, byte size and staged filename, plus an explicit notice that the recovered output is not approved or publishable until a human reviewer completes the normal review and separate approval process. Use the hash when comparing the staged file with the recovery record; do not treat provenance display as a rights, factuality or platform-policy certification.


## BUILD-00177 — Review decision and publication handoff

- A recovered render is adopted only into `review_pending`; inspect the recovered provider-attempt provenance and current quality/policy reports before deciding.
- Approve, reject or request revision only through the authenticated review decision action. The review ledger, production run and matching `short_video_production` queue row are synchronized in one SQLite transaction. A mismatched queue state is a conflict and must be reconciled; do not edit either table manually to force approval.
- Every synchronized decision emits a `job_events` record containing the reviewer identity and decision. Verify the production and queue statuses agree after the decision.
- Approval is not publication consent. YouTube upload and TikTok private posting remain separate operator-triggered actions; their publisher-specific policy, approval-snapshot, media-byte and consent checks remain mandatory. TikTok remains `SELF_ONLY` in this flow.
- Never infer successful upload/publication from review approval or queue status. Confirm the platform's returned/verified media ID and publication status in its respective operator workflow.


- If media staging or any other artifact change requires another review, the production review transition reopens an approved queue row to `review_pending` and records `review_reopened`. Confirm both ledgers are pending before taking the fresh approval; do not reuse the prior approval snapshot.


## BUILD-00178 — Production lifecycle integrity and recovery

The worker now runs a bounded production/queue state-integrity scan before claiming another job. Safe automatic repairs are deliberately narrow:
- Queue `cancelled` or `failed_terminal` is mirrored into a non-approved/non-uploaded production row.
- A durable queue `review_pending` handoff is mirrored only when the production row is still `rendered`.

Each repair appends a `production_state_reconciled` queue event. Approval and upload mismatches are never auto-promoted or guessed. If any mismatch remains unresolved, the worker persists a global pause and does not claim more work. An operator must inspect both ledgers and evidence, reconcile explicitly, and resume through the existing audited resume action.


## BUILD-00179 — Operator production integrity report

Use the authenticated read-only endpoint `GET /api/production/integrity-report?limit=50` with an operator token that grants `production.read`. The limit is clamped to 1–200. Each item shows the production and queue states, timestamps, queue error context, a classification, a recommended next action, and up to ten recent audit events. Event details are allowlisted; provider response bodies and arbitrary event payloads are not returned.

- `approval_or_upload_boundary`: inspect the human review decision and platform publication evidence. Never promote a state based only on the other ledger.
- `ambiguous_external_outcome`: only use `POST /api/production/jobs/{job_id}/reconcile-retry` after evidence proves no external side effect occurred. The global pause remains in place.
- Other mismatches: inspect both ledgers and the audit history; do not retry or resume based on the report alone.

This endpoint is strictly read-only. It does not reconcile records, resume workers, approve content, upload media, or publish to YouTube/TikTok. Queue resume remains a separate explicit audited operator action after all affected work is reviewed.


## BUILD-00180 — Dashboard integrity diagnostics

The Operations workspace includes a read-only **제작 상태 무결성** panel backed by `GET /api/production/integrity-report?limit=50`. Refresh it manually with **진단 갱신** or use the normal authenticated dashboard refresh. The panel displays both ledger states and timestamps, classification, queue error context, recommended action, and expandable recent audit chronology. All server-provided text is HTML-escaped before display.

The panel is intentionally diagnostic only. It does not repair mismatches, retry provider work, approve content, resume the queue, upload media, or publish to a platform. Follow the API/runbook evidence procedure and use the separate audited operator controls only after investigation.


## BUILD-00181 — Integrity report access control

The integrity report requires the `production.read` permission. A configured reviewer role has read access; an analyst role without that permission must receive HTTP 403. Missing or invalid credentials receive HTTP 401. The endpoint must not call the report store for denied or unauthenticated requests. This behavior is covered by the BUILD-00181 API security regression test.


## BUILD-00182 — Orphan lifecycle records

The integrity report scans three cases: state mismatches, short-video queue jobs with no production row, and production rows with no matching short-video queue job. Queue-only records are normally restored only by the existing payload-validated recovery path. If they remain missing after that path, the worker pauses and requires operator investigation. Production-only records are never converted into queue jobs automatically.

The report is bounded (maximum 200 records per call) and read-only. It does not create, delete, retry, approve, upload, or publish records. The worker blocks new claims when an orphan remains after recovery. A displayed limit is a scan bound, not a complete inventory count.


## BUILD-00183 — Integrity report totals and bounded samples

The integrity report's `unresolved` and `orphaned` fields are aggregate counts across the full matching tables, not just the displayed sample. `scanned` is the number of detail rows returned, `has_more` indicates that the sample is truncated, and `counts` breaks the totals into state mismatches, queue-only rows, and production-only rows.

Detail rows remain capped at 200. Orphan rows are prioritized in the sample so the worker's bounded safety check sees orphan records before ordinary status mismatches. The dashboard labels the total separately from the displayed detail count; a truncated report is not a complete item listing.


## BUILD-00184 — Paginated integrity report

The integrity endpoint accepts `limit` (1–200) and `offset` (0–1,000,000). Aggregate counts always describe the full matching set; `scanned` describes only the current page. When `has_more` is true, `next_offset` identifies the next page. The Operations panel appends pages with **다음 50건 더 보기** while retaining orphan-first ordering.

Refresh the diagnostic report to restart from the first page after new events or state changes. Pagination is read-only and does not change lifecycle state.


## BUILD-00185 — Stable integrity report pagination

The Operations dashboard uses an opaque `next_cursor` token. Cursor ordering is based on the orphan/mismatch group and immutable job ID, not mutable update timestamps. This prevents a record changing its timestamp between page requests from moving across the already-read page boundary. Legacy `offset` pagination remains available for API compatibility but is not used by the dashboard.

A cursor is a continuation position, not a frozen database snapshot: newly created or resolved inconsistencies can change aggregate totals while an operator is paging. Refresh the report to restart from the current first page.


## BUILD-00186 — Batched audit history lookup

Integrity report pages now fetch audit history for all displayed job IDs in one query and use a per-job rank to return at most the 10 newest events per record. The response still presents those events chronologically and retains the existing details allowlist. This avoids issuing one extra SQL query per displayed row while keeping the result bounded by the page size and per-job event cap.


## BUILD-00187 — Diagnostic error redaction

The production integrity report intentionally withholds raw queue error text. Provider HTTP response bodies and exception details can contain credentials, signed URLs, or customer data. The report returns the controlled error code and a fixed message directing authorized operators to protected server logs; raw error text remains stored for restricted diagnostics and is not copied into this read-only report.


## BUILD-00306 — Resume gate for unresolved provider outcomes

Before calling `POST /api/queue/resume`, reconcile **every** production job whose external provider outcome is ambiguous. The resume transaction counts all unresolved queue records, not only the first page returned by the diagnostic listing. If any remain, the API returns HTTP 409 and the global pause stays active.

For each affected job:
1. Inspect the provider request history, usage/billing evidence and any recovered response/artifact.
2. If evidence confirms no external side effect, use the audited `POST /api/production/jobs/{job_id}/reconcile-retry` action with the provider evidence reference and investigation note.
3. If the provider completed the work, do not authorize a retry. Preserve the provider result and escalate for manual result adoption/reconciliation; the resume gate intentionally remains closed until that ambiguity is resolved through a supported workflow.
4. After all ambiguous jobs have been reconciled, submit the separate queue resume action with a new operator note.

A retry authorization does not resume production. Conversely, a non-empty resume note alone is not sufficient to resume while any ambiguous job remains. The database check and pause-clear transition execute in one SQLite write transaction.


## BUILD-00307 — transcription provider crash recovery

The optional `speech_alignment` transcription call participates in the same provider-attempt journal as script, voice and rendering. Before making the external request, the worker persists a request idempotency key. A response is durably stored before the speech-alignment artifact is written and the attempt is marked adopted.

When recovering:
- If the attempt is `response_received`, the worker reuses the stored response and does not submit another transcription request.
- If the attempt is `request_started` or `outcome_unknown`, do not retry automatically. Investigate the transcription provider using its request/idempotency reference and reconcile the attempt using the supported provider-attempt reconciliation workflow.
- A provider's actual deduplication behavior for the supplied idempotency key must be confirmed from that provider's documentation/configuration; the local journal alone cannot guarantee remote deduplication.
