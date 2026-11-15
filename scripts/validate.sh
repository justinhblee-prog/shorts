#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../backend"
python -m compileall -q .
python -m unittest discover -s tests -v
