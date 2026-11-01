#!/usr/bin/env bash
# Hot-reload development: backend on :8000, Vite on :5173 (proxies /api and /ws).
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000) &
BACK=$!
trap 'kill $BACK' EXIT
cd frontend && npm run dev
