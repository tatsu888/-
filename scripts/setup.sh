#!/usr/bin/env bash
# One-time setup (macOS / Linux / WSL). Requires Python 3.11+ and Node 20+.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
(cd frontend && npm install)
echo "setup done. Next: scripts/start.sh  (or scripts/dev.sh for hot reload)"
