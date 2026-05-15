@echo off
cd /d C:\Users\matti\Desktop\prediction-market-analysis
set PYTHONUNBUFFERED=1
set LOCKFILE=watchdog_esports.lock

:: Prevent multiple instances — exit immediately if lock exists
if exist %LOCKFILE% (
    echo [%date% %time%] Already running (lock exists). Exiting. >> watchdog_esports.log
    exit /b 1
)

:: Create lock file
echo %RANDOM%%RANDOM% > %LOCKFILE%

:loop
echo [%date% %time%] Starting esports_fade_bot (PAPER)... >> watchdog_esports.log
.venv\Scripts\python.exe -u esports_fade_bot.py >> watchdog_esports.log 2>&1
echo [%date% %time%] Bot exited (code %errorlevel%) - restarting in 10s... >> watchdog_esports.log
timeout /t 10 /nobreak >nul
goto loop
