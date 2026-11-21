# Development monitor browser smoke

The smoke test serves the actual NEXUS frontend against a disposable local fixture API. It does not connect to the production database or external services.

## Run

```powershell
python -m pip install -r backend/requirements.txt
npm install --no-save playwright@1.56.1
npx playwright install chromium
node scripts/ui_development_monitor_smoke.mjs
```

The script starts and stops `scripts/ui_development_monitor_smoke_server.py`, verifies unauthenticated and invalid-token behavior, then exercises the authenticated monitor summary, status filter, job selection and event-history switching. It also checks that lease tokens, runner hostnames and private event details never render and that the monitor issues only GET requests.

Screenshots are written to `artifacts/development-monitor-desktop.png` and `artifacts/development-monitor-mobile.png`.
