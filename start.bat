@echo off
chcp 65001 >/dev/null
title Stock System

cd /d "%~dp0"
echo Path: %CD%

python --version >/dev/null 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing packages...
pip install -q -r requirements.txt --upgrade-strategy only-if-needed

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 "') do (
    taskkill /F /PID %%a >/dev/null 2>&1
)

start "" cmd /c "timeout /t 5 >/dev/null && start http://127.0.0.1:8000"

echo.
echo Dashboard: http://127.0.0.1:8000
echo Close this window to stop.
echo.

.venv\Scripts\uvicorn.exe backend.main:app --host 0.0.0.0 --port 8000

pause