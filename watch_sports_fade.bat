@echo off
REM Watchdog for sports_fade_bot. v1.36 (2026-05-27): switched from PAPER-only
REM to --live. LIVE orders are restricted to LIVE_SPORTS_PREFIXES (MLB only);
REM other sports continue paper-logging for data collection.
setlocal
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"

set LOCKFILE=watchdog_sports.lock
set LOGFILE=watchdog_sports.log

:: self-heal stale lock (see watch_esports_fade.bat) — never let a leftover lock
:: from a crash/reboot permanently block restart.
if exist %LOCKFILE% del /f /q %LOCKFILE%
echo %date% %time% > %LOCKFILE%

:loop
echo [%date% %time%] Starting sports_fade_bot ^(LIVE on MLB, paper on others^)... >> %LOGFILE%
.venv\Scripts\python.exe -u sports_fade_bot.py --live >> %LOGFILE% 2>&1
echo [%date% %time%] Bot exited (code %errorlevel%) - restart in 10s... >> %LOGFILE%
timeout /t 10 /nobreak > nul
goto loop
