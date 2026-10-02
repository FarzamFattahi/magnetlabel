@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setting up MagnetLabel for the first time...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
  if errorlevel 1 goto setup_error
)
if not exist ".venv\magnetlabel-ready.txt" (
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 goto setup_error
  echo ready > ".venv\magnetlabel-ready.txt"
)
".venv\Scripts\python.exe" -m magnetlabel.cli %*
if errorlevel 1 pause
exit /b
:setup_error
echo Setup failed. Install Python 3.11 or newer, or use the ready-to-run Windows download.
pause
exit /b 1
