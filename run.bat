@echo off
setlocal

rem ============================================================
rem  Jangbaguni Yebo AI - launcher (Windows)
rem  ASCII-only on purpose: Korean text in a .bat desyncs the
rem  cmd parser under the cp949 codepage. App UI stays Korean.
rem  Uses existing streamlit if present; builds .venv only if not.
rem ============================================================

cd /d "%~dp0"

echo.
echo ===== Jangbaguni Yebo AI =====
echo.

rem --- Python check ---
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo         Install from https://www.python.org and enable "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

rem --- Pick interpreter: existing .venv first, else global python ---
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

rem --- Ensure streamlit; build .venv + install only when missing ---
"%PY%" -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] streamlit missing - creating .venv and installing deps... ^(first run, a few minutes^)
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] dependency install failed ^(check network/proxy^).
        pause
        exit /b 1
    )
    set "PY=.venv\Scripts\python.exe"
) else (
    echo [OK] streamlit already installed - launching directly.
)

rem --- Secrets notice (sample demo works without it) ---
if not exist ".streamlit\secrets.toml" (
    echo [INFO] .streamlit\secrets.toml not found - running on sample demo data.
    echo        For real data, copy secrets.toml.example to secrets.toml and fill keys.
)

rem --- Launch ---
echo.
echo [RUN] Streamlit app - browser: http://localhost:8501
echo       Press Ctrl+C in this window to stop.
echo.
"%PY%" -m streamlit run app.py

echo.
echo [STOPPED] Press any key to close this window.
pause >nul
endlocal
