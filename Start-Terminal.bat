@echo off
REM Analyst Terminal — double-click launcher for Windows.
REM First run: creates the Python venv, installs packages (incl. xlwings) and builds the UI.
REM Then starts the server on http://localhost:8000 and opens the browser.
REM Optional: set your Excel model folder below (semicolon separated) before double-clicking.
REM set TERMINAL_EXCEL_DIRS=C:\Users\%USERNAME%\Documents\Models

cd /d "%~dp0"
if not exist "backend\.venv\Scripts\python.exe" (
  echo [setup] first run - installing Python packages and building the UI ...
  powershell -ExecutionPolicy Bypass -File "scripts\setup.ps1" || goto :fail
)
if not exist "frontend\dist\index.html" (
  echo [build] building the UI ...
  pushd frontend && call npm run build && popd || goto :fail
)
start "" "http://localhost:8000"
cd backend
".venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000
goto :eof

:fail
echo.
echo Setup failed. Requirements: Python 3.11+ and Node.js 20+ on PATH. See README.md.
pause
