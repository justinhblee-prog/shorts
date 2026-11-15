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
- **Operations:** configure interval schedules, record verified financial entries, and inspect snapshot-based performance insights.

## Services

| Service | Purpose |
|---|---|
| API | FastAPI dashboard and protected operational endpoints |
| Worker | Claims and executes short-video production jobs |
| Scheduler | Dispatches due interval schedules into the durable queue |

All services share the persistent `nexus_data` volume. Run only one scheduler instance. This is a single-host SQLite baseline, not a horizontally scalable production deployment.

## Validation

With Python dependencies installed:

```bash
sh scripts/validate.sh
```

This runs Python bytecode compilation and unittest discovery. The GitHub Actions runner has repeatedly failed before runner allocation (`runner_id=0`, no steps); therefore do not assume the suite has passed until a run actually executes the test steps.

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
