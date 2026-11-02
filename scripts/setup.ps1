# One-time setup on Windows (PowerShell). Requires Python 3.11+ and Node 20+.
Set-Location (Join-Path $PSScriptRoot "..")
python -m venv backend\.venv
backend\.venv\Scripts\pip install -r backend\requirements-dev.txt
# Windows: edit Excel from the terminal through the real Excel app (lossless). Requires desktop Excel.
backend\.venv\Scripts\pip install xlwings
Push-Location frontend; npm install; Pop-Location
Write-Host "setup done. Next: scripts\start.ps1"
