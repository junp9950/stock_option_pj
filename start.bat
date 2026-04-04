@echo off
chcp 65001 >nul
title 선물옵션 수급 시스템

echo ========================================
echo  선물·옵션 수급 기반 종목 선별 시스템
echo ========================================
echo.

:: Python 설치 확인
python --version >nul 2>&1
if errorlevel 1 (
    echo [오류] Python이 설치되어 있지 않습니다.
    echo https://www.python.org/downloads/ 에서 Python 3.10 이상을 설치하세요.
    pause
    exit /b 1
)

:: 스크립트 위치로 이동
cd /d "%~dp0"

:: 가상환경 없으면 생성
if not exist ".venv\Scripts\activate.bat" (
    echo [1/3] 가상환경 생성 중...
    python -m venv .venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패
        pause
        exit /b 1
    )
)

:: 가상환경 활성화
call .venv\Scripts\activate.bat

:: 패키지 설치 (requirements.txt 기준, 이미 있으면 스킵)
echo [2/3] 패키지 확인 중...
pip install -q -r requirements.txt --upgrade-strategy only-if-needed
if errorlevel 1 (
    echo [오류] 패키지 설치 실패
    pause
    exit /b 1
)

:: 포트 8000 사용 중이면 해제
echo [3/3] 서버 시작 중...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 "') do (
    taskkill /F /PID %%a >nul 2>&1
)

:: 3초 후 브라우저 자동 열기
start "" cmd /c "timeout /t 4 >nul && start http://127.0.0.1:8000"

echo.
echo  대시보드: http://127.0.0.1:8000
echo  종료하려면 이 창을 닫으세요.
echo.

:: 서버 시작
uvicorn backend.main:app --host 0.0.0.0 --port 8000

pause
