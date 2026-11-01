# Build the frontend and serve on http://localhost:8000 (Windows).
# Example: $env:TERMINAL_EXCEL_DIRS="C:\Users\me\Models"; .\scripts\start.ps1
Set-Location (Join-Path $PSScriptRoot "..")
Push-Location frontend; npm run build; Pop-Location
Set-Location backend
.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
