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

- [ ] Complete `sh scripts/validate.sh` successfully in a real Python 3.11+ environment.
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


### Ambiguous production worker loss — fail-closed recovery

- A short-video production job whose worker lease expires is **not automatically requeued**. The provider may have completed an external side effect even if the worker died before persisting its result.
- Expired production work is moved to `failed_terminal` with `production_lease_expired_ambiguous`; the matching production record is synchronized and the production queue is durably paused.
- A normal worker interruption (Ctrl+C) during provider execution records a non-retriable ambiguous failure, pauses production, and exits. A hard process/host kill is handled by the lease-expiry path on the next claim or recovery.
- Operators must inspect the provider's job history and billing/artifact state before deciding whether to create a new production request. Do not simply retry the same ambiguous job.
- Non-production queue jobs retain their existing lease-expiry retry behavior.
