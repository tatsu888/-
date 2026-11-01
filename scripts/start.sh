#!/usr/bin/env bash
# Build the frontend and serve everything from FastAPI on http://localhost:8000
# Data source: TERMINAL_PROVIDER=tradingview|yahoo|sim (can also be switched in the UI).
set -euo pipefail
cd "$(dirname "$0")/.."
(cd frontend && npm run build)
cd backend
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
