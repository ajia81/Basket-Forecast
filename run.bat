@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ============================================================
rem  장바구니 예보 AI — 실행 스크립트 (Windows)
rem  최초 실행 시: 가상환경 생성 + 의존성 설치 후 앱 구동
rem  이후 실행 시: 바로 앱 구동
rem ============================================================

cd /d "%~dp0"

echo.
echo ===== 장바구니 예보 AI =====
echo.

rem --- Python 확인 ---
where python >nul 2>nul
if errorlevel 1 (
    echo [오류] Python 을 찾을 수 없습니다.
    echo        https://www.python.org 에서 설치 후 "Add Python to PATH" 를 켜주세요.
    echo.
    pause
    exit /b 1
)

rem --- 가상환경(.venv) 준비 ---
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 가상환경(.venv) 생성 중...
    python -m venv .venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패.
        pause
        exit /b 1
    )
    echo [2/3] 의존성 설치 중... ^(최초 1회, 수 분 소요^)
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [오류] 의존성 설치 실패.
        pause
        exit /b 1
    )
) else (
    echo [건너뜀] 가상환경이 이미 있습니다.
)

rem --- 시크릿 파일 안내 (없어도 폴백 데이터로 동작) ---
if not exist ".streamlit\secrets.toml" (
    echo.
    echo [안내] .streamlit\secrets.toml 이 없습니다.
    echo        실데이터 연동 없이 폴백 데이터로 동작합니다.
    echo        실연동하려면 secrets.toml.example 을 복사해 키를 채우세요.
)

rem --- 앱 실행 ---
echo.
echo [3/3] Streamlit 앱 실행... ^(브라우저: http://localhost:8501^)
echo        종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py

endlocal
