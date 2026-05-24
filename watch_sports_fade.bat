@echo off
REM Watchdog for sports_fade_bot (PAPER mode). Auto-restarts if it crashes.
setlocal
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"

set LOCKFILE=watchdog_sports.lock
set LOGFILE=watchdog_sports.log

if exist %LOCKFILE% (
    echo [%date% %time%] Already running. Exiting. >> %LOGFILE%
    exit /b 1
)
echo %date% %time% > %LOCKFILE%

:loop
echo [%date% %time%] Starting sports_fade_bot ^(PAPER^)... >> %LOGFILE%
.venv\Scripts\python.exe -u sports_fade_bot.py >> %LOGFILE% 2>&1
echo [%date% %time%] Bot exited (code %errorlevel%) - restart in 10s... >> %LOGFILE%
timeout /t 10 /nobreak > nul
goto loop
