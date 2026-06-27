@echo off
chcp 65001 >nul

rem ============================================================
rem  장바구니 예보 AI — 회귀 테스트 (pytest)
rem  로직(bf/core.py, bf/data.py) 변경 시 반드시 통과 유지
rem ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [오류] 가상환경이 없습니다. 먼저 run.bat 을 한 번 실행하세요.
    pause
    exit /b 1
)

echo [설치] 개발 의존성 확인 중...
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt >nul

echo.
echo [테스트] python -m pytest -q
echo.
".venv\Scripts\python.exe" -m pytest -q

echo.
pause
