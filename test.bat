@echo off
setlocal

rem ============================================================
rem  Jangbaguni Yebo AI - regression tests (pytest)
rem  ASCII-only on purpose (cmd cp949 parser safety).
rem  Uses existing .venv if present, else global python.
rem ============================================================

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://www.python.org first.
    pause
    exit /b 1
)

set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo [SETUP] ensuring dev dependencies...
"%PY%" -m pip install -r requirements-dev.txt >nul

echo.
echo [TEST] %PY% -m pytest -q
echo.
"%PY%" -m pytest -q

echo.
pause
