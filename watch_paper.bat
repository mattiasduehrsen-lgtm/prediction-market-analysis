@echo off
cd /d C:\Users\matti\Desktop\prediction-market-analysis
set PYTHONUNBUFFERED=1
set LOCKFILE=watchdog_paper.lock

:: Prevent multiple instances — exit immediately if lock exists
if exist %LOCKFILE% (
    echo [%date% %time%] Already running (lock exists). Exiting. >> watchdog_paper.log
    exit /b 1
)

:: Create lock file with current PID
echo %RANDOM%%RANDOM% > %LOCKFILE%

:loop
echo [%date% %time%] Starting multi-loop... >> watchdog_paper.log
.venv\Scripts\python.exe -u main.py multi-loop >> watchdog_paper.log 2>&1
echo [%date% %time%] Bot exited (code %errorlevel%) - restarting in 10s... >> watchdog_paper.log
timeout /t 10 /nobreak >/dev/null
goto loop
