@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
set LOCKFILE=watchdog_cs2model.lock
:: self-heal: delete any STALE lock from a crashed/rebooted instance instead of
:: exiting on it (that trap silently killed this bot for 2 days, 2026-06-05->07).
:: The scheduled task's own instance control prevents true double-runs.
if exist %LOCKFILE% del /f /q %LOCKFILE%
echo %date% %time% > %LOCKFILE%
:loop
echo [%date% %time%] starting cs2_model_bot >> watchdog_cs2model.log
.venv\Scripts\python.exe -u cs2_model_bot.py >> watchdog_cs2model.log 2>&1
echo [%date% %time%] exited (code %errorlevel%) restart 10s >> watchdog_cs2model.log
timeout /t 10 /nobreak > nul
goto loop
