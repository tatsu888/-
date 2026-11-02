# Check TradingView / Yahoo connectivity and every configured symbol (Windows).
# Paste the printed table (or diagnose_report.json) into ChatGPT/Claude together with docs/HANDOFF.md.
Set-Location (Join-Path $PSScriptRoot "..\backend")
.\.venv\Scripts\python -m app.diagnose --json ..\diagnose_report.json @args
