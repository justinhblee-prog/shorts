#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../backend"
python -m compileall -q .
if command -v node >/dev/null 2>&1; then node --check ../frontend/app.js; fi
python ../scripts/check_frontend_ids.py
python -m unittest discover -s tests -v
