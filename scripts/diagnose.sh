#!/usr/bin/env bash
# Check TradingView / Yahoo connectivity and every configured symbol; writes diagnose_report.json
set -euo pipefail
cd "$(dirname "$0")/../backend"
.venv/bin/python -m app.diagnose --json ../diagnose_report.json "$@"
