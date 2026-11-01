#!/usr/bin/env bash
# All checks that must pass before committing.
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && .venv/bin/python -m pytest -q)
(cd frontend && npx tsc -b && npx vitest run && npx vite build)
