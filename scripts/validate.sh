#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../backend"
python -m compileall -q .
python -m py_compile ../scripts/devflow.py ../scripts/devflow_autopilot.py ../scripts/devflow_parallel.py
python -m json.tool ../.devflow/tasks.json > /dev/null
if python -c "import yaml" >/dev/null 2>&1; then
  python -c "import yaml; yaml.safe_load(open('../compose.yaml', encoding='utf-8'))"
else
  echo "WARNING: PyYAML is not installed; compose.yaml syntax validation is delegated to Linux CI."
fi
if command -v node >/dev/null 2>&1; then node --check ../frontend/app.js; fi
python ../scripts/check_frontend_ids.py
python -m unittest discover -s tests -v
