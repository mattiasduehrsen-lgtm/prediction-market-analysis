@echo off
REM Watchdog for the Telegram command bot. Auto-restarts if it crashes.
setlocal
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"

set LOCKFILE=watchdog_telegram.lock
set LOGFILE=watchdog_telegram.log

if exist %LOCKFILE% (
    echo [%date% %time%] Already running. Exiting. >> %LOGFILE%
    exit /b 1
)
echo %date% %time% > %LOCKFILE%

:loop
echo [%date% %time%] Starting telegram_bot... >> %LOGFILE%
.venv\Scripts\python.exe -u telegram_bot.py >> %LOGFILE% 2>&1
echo [%date% %time%] Bot exited (code %errorlevel%) - restart in 10s... >> %LOGFILE%
timeout /t 10 /nobreak > nul
goto loop
