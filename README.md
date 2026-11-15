# NEXUS STUDIO PRO

Global short-form content operations platform. The system coordinates topic discovery, competitor intelligence, profitability scenarios, AI production providers, human review, private YouTube uploads, and source-backed revenue/cost tracking.

## Run locally with Docker

1. Copy `.env.example` to `.env`.
2. Set a long random `NEXUS_REVIEW_TOKEN`.
3. Configure the script, voice and render provider endpoints/tokens.
4. Set `RENDER_ARTIFACT_HOSTS` to the exact HTTPS CDN hostnames returned by your renderer.
5. Add YouTube OAuth refresh credentials with `youtube.upload`, `youtube.readonly` and `yt-analytics.readonly` scopes, plus the YouTube Data API key. Enable the YouTube Analytics API in Google Cloud and reauthorize the channel after adding the Analytics scope.
6. Register TikTok Login Kit, Content Posting API and Display API, configure the exact HTTPS callback URI, set TikTok client credentials, and generate a stable Fernet encryption key as shown in `.env.example`. TikTok metrics additionally require creator consent to the `video.list` scope; existing connections must reauthorize after this scope is added.
7. Start the services:

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
- **TikTok:** connect the creator account from Integration Readiness. OAuth state is one-time and expires after ten minutes; access/refresh tokens are encrypted in SQLite, access tokens refresh proactively, and rotated refresh tokens replace the previous value. Direct Post is fixed to `SELF_ONLY`. The Display API collector separately requires `video.list` consent and records views, likes, comments and shares for confirmed owned publications.
- **Ambiguous upload recovery:** if a resumable upload times out after starting, automatic retries are blocked. Check YouTube Studio and use the dashboard reconciliation action after the stale threshold (`NEXUS_UPLOAD_STALE_SECONDS`, default 900 seconds).
- **Operations:** configure interval schedules, record verified financial entries, inspect snapshot-based performance insights, and pause/resume production with an audited operator note.
- **Metrics collection:** the separate `metrics-collector` service independently refreshes YouTube Data API counters, YouTube Analytics reports and TikTok counters, records collection health/coverage, and isolates provider failures. YouTube Analytics adds engaged views, watch time, average view duration/percentage, likes, comments, shares and subscribers gained, requiring `yt-analytics.readonly`. TikTok collection requires `video.list`; only views, likes, comments and shares are reported. Detailed retention curves, swipe-away and revenue are not inferred.
- **Recommendation experiments:** chronological holdout splits complete recommendation exposure runs, reports pre/holdout association stability, and supports operator-captured immutable evaluation snapshots with input fingerprints. Outcomes remain observational and selection-biased; ranking scores are not auto-adjusted.

## Services

| Service | Purpose |
|---|---|
| API | FastAPI dashboard and protected operational endpoints |
| Worker | Claims and executes short-video production jobs |
| Scheduler | Dispatches due interval schedules into the durable queue |
| Metrics collector | Independently refreshes due YouTube and TikTok counters and records collection health |

All services share the persistent `nexus_data` volume. The scheduler uses a SQLite singleton leader lease with a fencing token, so multiple instances can safely run with only one active dispatcher; crashed leaders are replaced after lease expiry. This remains a single-host SQLite baseline, not a horizontally scalable multi-host production deployment.

## Validation

With Python dependencies installed:

```bash
sh scripts/validate.sh
```

This runs Python bytecode compilation, unittest discovery, and (when Node.js is available) JavaScript syntax validation. Latest verified code validation including BUILD-00093: GitHub Actions PR run [43730353235](https://github.com/justinhblee-prog/shorts/actions/runs/43730353235), **545 tests passed**; frontend validation reported 107 unique IDs / 91 literal selectors. This validates automated checks only, not live provider connectivity, OAuth consent, real-account publishing, metric retrieval or monetization. Validation includes Python compilation, frontend JavaScript syntax/DOM ID checks and Docker Compose YAML parsing. This verifies automated checks only, not live provider connectivity, deployed browser behavior, YouTube OAuth/upload, or financial reconciliation.

## Documentation

- [Build status](docs/BUILD_STATUS.md)
- [Technical handover](docs/HANDOVER.md)
- [Operator runbook](docs/OPERATOR_RUNBOOK.md)
- [Backend/API reference](backend/README.md)

## Non-negotiable operating constraints

- No public publishing action is exposed. YouTube uploads remain `private`; TikTok Direct Post remains `SELF_ONLY`.
- A recorded human approval is required before upload.
- Forecasts are estimates, not actual earnings.
- Missing source metrics remain missing; no fabricated views, RPM, trend volume or revenue.
- Real AI generation, OAuth, YouTube upload, and real financial reconciliation require external credentials and validation.


### Recommendation experiments (shadow-only)
Authenticated operator endpoints:
- `POST /api/recommendations/experiments` creates a draft control/treatment experiment.
- `GET /api/recommendations/experiments` lists definitions and shadow assignment counts.
- `POST /api/recommendations/experiments/{experiment_id}/shadow-assignment` computes a stable assignment without serving a variant.
- `GET /api/recommendations/experiments/{experiment_id}/report` reports assignment counts and explicit evidence gaps.

Live assignment, recommendation changes, causal-effect claims and ranking-score adjustments are disabled. Shadow assignment is not an exposure.


### Recommendation viewport exposure evidence
- The recommendation workspace records a privacy-minimized viewport acknowledgement after a card is at least 50% visible for at least one second.
- Authenticated `POST /api/recommendations/exposures/rendered` accepts immutable, idempotent render events linked to a captured recommendation run; `GET /api/recommendations/exposures/{run_id}/report` summarizes rendered cards and eligible post-render measured outcomes.
- These are client-reported render acknowledgements, not proof of attention or randomized experiment exposure. No experiment arm is served and no ranking adjustment is enabled.
