@echo off
cd /d C:\Users\matti\Desktop\prediction-market-analysis
set PYTHONUNBUFFERED=1
set LOCKFILE=watchdog_esports.lock

:: Self-heal stale lock: a leftover lock from a crashed/rebooted instance must
:: NOT permanently block restart (that trap silently killed cs2_model for 2 days,
:: and on reboot would block EVERY onstart watchdog incl. this LIVE bot). The
:: scheduled task's own instance control prevents true double-runs.
if exist %LOCKFILE% del /f /q %LOCKFILE%

:: Create lock file
echo %RANDOM%%RANDOM% > %LOCKFILE%

:loop
echo [%date% %time%] Starting esports_fade_bot (PAPER)... >> watchdog_esports.log
.venv\Scripts\python.exe -u esports_fade_bot.py >> watchdog_esports.log 2>&1
echo [%date% %time%] Bot exited (code %errorlevel%) - restarting in 10s... >> watchdog_esports.log
timeout /t 10 /nobreak >nul
goto loop
