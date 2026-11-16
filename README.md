# NEXUS STUDIO PRO

Global short-form content operations platform. The system coordinates topic discovery, competitor intelligence, profitability scenarios, AI production providers, human review, private YouTube uploads, and source-backed revenue/cost tracking.

## Run locally with Docker

1. Copy `.env.example` to `.env`.
2. Set a long random `NEXUS_REVIEW_TOKEN`.
3. Configure the script, voice and render provider endpoints/tokens.
4. Set `RENDER_ARTIFACT_HOSTS` to the exact HTTPS CDN hostnames returned by your renderer.
5. Add YouTube OAuth refresh credentials and YouTube Data API key when ready.
6. Start the services:

```bash
docker compose build
docker compose up -d
docker compose ps
```

Open the single-page operations dashboard at **http://localhost:8502/**. Enter the review token using the settings control. It is held in browser memory only and is cleared on refresh.

## Operations dashboard

- **Studio:** create a production job for one of the ten brands.
- **Intelligence:** collect Google News/Hacker News signals, search competitor channels, and score attributed profitability scenarios.
- **Review:** inspect actual provider-generated video references; approve, reject or request revisions.
- **Approved uploads:** stage the saved MP4 artifact from an allowlisted HTTPS host and explicitly initiate a YouTube upload. Upload privacy is always `private`.
- **Ambiguous upload recovery:** if a resumable upload times out after starting, automatic retries are blocked. Check YouTube Studio and use the dashboard reconciliation action after the stale threshold (`NEXUS_UPLOAD_STALE_SECONDS`, default 900 seconds).
- **Operations:** configure interval schedules, record verified financial entries, inspect snapshot-based performance insights, and pause/resume production with an audited operator note.

## Services

| Service | Purpose |
|---|---|
| API | FastAPI dashboard and protected operational endpoints |
| Worker | Claims and executes short-video production jobs |
| Scheduler | Dispatches due interval schedules into the durable queue |

All services share the persistent `nexus_data` volume. The scheduler uses a SQLite singleton leader lease with a fencing token, so multiple instances can safely run with only one active dispatcher; crashed leaders are replaced after lease expiry. This remains a single-host SQLite baseline, not a horizontally scalable multi-host production deployment.

## Validation

With Python dependencies installed:

```bash
sh scripts/validate.sh
```

This runs Python bytecode compilation, unittest discovery, and (when Node.js is available) JavaScript syntax validation. Latest verified CI is GitHub Actions run [43789858034](https://github.com/justinhblee-prog/shorts/actions/runs/43789858034), which passed **365 backend tests** and `scripts/validate.sh` on BUILD-00038 restore hardening. CI validates automated logic only, not live provider connectivity, deployed browser behavior, YouTube OAuth/upload, scheduled backup operations or a production restore drill. Validation includes Python compilation, frontend JavaScript syntax/DOM ID checks and Docker Compose YAML parsing. This verifies automated checks only, not live provider connectivity, deployed browser behavior, YouTube OAuth/upload, or financial reconciliation.

## Documentation

- [Build status](docs/BUILD_STATUS.md)
- [Technical handover](docs/HANDOVER.md)
- [Operator runbook](docs/OPERATOR_RUNBOOK.md)
- [Backend/API reference](backend/README.md)

## Non-negotiable operating constraints

- No public upload or publishing action is exposed. YouTube uploads remain private.
- A recorded human approval is required before upload.
- Forecasts are estimates, not actual earnings.
- Missing source metrics remain missing; no fabricated views, RPM, trend volume or revenue.
- Real AI generation, OAuth, YouTube upload, and real financial reconciliation require external credentials and validation.


### TikTok operator workflow

The review workspace includes a TikTok connection action, creator capability display, private-only publishing action, status refresh/reconciliation controls, and a metrics panel. Posting requires a human-approved job, an unchanged approved media fingerprint, a connected TikTok account, a creator-info lookup, explicit operator consent, and `SELF_ONLY` privacy. The approved queue remains visible until both platform publication records are complete. OAuth and live account checks require the operator's TikTok developer credentials and account consent.


### Platform-specific recommendation evidence

The trend workspace supports separate YouTube Shorts and TikTok recommendation exposures. TikTok performance analysis uses owned-video Display API snapshots only (views, likes, comments, shares), computes time-normalized view velocity and interaction-rate deltas, and forms comparable brand/region/topic/duration/format/publication-age cohorts. Recommendation exposures and production selections are tagged and evaluated within their platform; YouTube outcomes are never mixed with TikTok outcomes. Score adjustment remains disabled until the required within-exposure holdout sample is available. TikTok Display API data in this collector does not provide audience retention, watch time or estimated revenue, so those metrics are not inferred.


### Platform-aware scheduled production

Manual production requests and recurring schedules let the operator select YouTube Shorts or TikTok. The platform selection is persisted in the schedule payload and survives the durable scheduler outbox and queue dispatch, so downstream production policy checks and approval/publishing gates receive the intended target platform. YouTube remains the default for existing schedules and older payloads.


YouTube Shorts performance insights now support authenticated YouTube Analytics reports for average view duration, average view percentage and per-video audience-retention curves. These are separate from public Data API counter snapshots and remain unavailable until the configured channel refresh token has the required Analytics permission and the API returns eligible data. Metrics are shown as evidence only; recommendation ranking is not automatically changed.


BUILD-00032 YouTube Analytics integration passed **336 backend tests** in GitHub Actions run [43785987107](https://github.com/justinhblee-prog/shorts/actions/runs/43785987107). Live channel consent, real Analytics responses and eligible retention curves remain deployment checks.


Recommendation analysis now exposes topic-matched YouTube watch-quality evidence and separate holdout diagnostics for average view percentage, average view duration and audience-retention checkpoints. These metrics are not blended into views/hour or used to change ranking scores; only future evidence-backed controlled evaluation can justify that.


BUILD-00033 added retention-aware topic context and independent holdout diagnostics for average view percentage, average view duration and 25/50/75% audience-watch checkpoints. CI passed **338 backend tests** in [run 43786466302](https://github.com/justinhblee-prog/shorts/actions/runs/43786466302). Recommendation ranking remains unchanged pending real data and controlled evaluation.


Shorts performance reporting also tracks YouTube Analytics `engagedViews` separately from `views`, with a clearly labeled derived engaged-view share. This quality signal is displayed and evaluated in holdouts, but is not yet used to change recommendation rankings.


BUILD-00034 adds YouTube Shorts engagedViews as a separate quality signal and displays a derived engaged-view share without changing recommendation ranking. The implementation passed **339 backend tests** in [GitHub Actions run 43787047727](https://github.com/justinhblee-prog/shorts/actions/runs/43787047727).


YouTube account connection now supports a server-side OAuth flow with one-time state, encrypted refresh-token storage and dashboard status controls. Live Google consent and account verification still require the operator's Google Cloud OAuth client and registered HTTPS callback.


BUILD-00036 added encrypted YouTube OAuth connection and dashboard controls. CI passed **352 backend tests** in [run 43788265493](https://github.com/justinhblee-prog/shorts/actions/runs/43788265493); live Google consent and channel verification remain deployment steps.


YouTube OAuth now has an explicit live verification action that checks the selected channel through Data API v3 and Analytics API v2 separately. OAuth token storage is not represented as live connectivity until these checks succeed.


BUILD-00037 adds a protected live verification action for YouTube Data API and Analytics API access. The implementation passed **356 backend tests** in [run 43788723765](https://github.com/justinhblee-prog/shorts/actions/runs/43788723765); actual channel verification still requires operator OAuth consent and execution.


Compose now includes an automated daily SQLite + media backup service with checksums, integrity validation, retention and an explicitly confirmed restore command. Backups are stored in a separate Docker volume and must be replicated off-host for disaster recovery; secrets are never included.


BUILD-00038 adds daily SQLite + media backups and a checksum-verified, explicitly confirmed restore path. Restore hardening passed **365 backend tests** in [run 43789858034](https://github.com/justinhblee-prog/shorts/actions/runs/43789858034); the backup service has not yet been deployed to a live host.


BUILD-00039 adds per-operator credentials, least-privilege role guards, authenticated reviewer identity and persistent API rate limiting. Forwarded client IPs are trusted only from explicitly configured proxy CIDRs.
