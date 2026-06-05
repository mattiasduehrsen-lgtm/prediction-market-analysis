@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
set LOCKFILE=watchdog_cs2inplay.lock
if exist %LOCKFILE% ( echo [%date% %time%] already running >> watchdog_cs2inplay.log & exit /b 1 )
echo %date% %time% > %LOCKFILE%
:loop
echo [%date% %time%] starting cs2_inplay_bot >> watchdog_cs2inplay.log
.venv\Scripts\python.exe -u cs2_inplay_bot.py >> watchdog_cs2inplay.log 2>&1
echo [%date% %time%] exited (code %errorlevel%) restart 10s >> watchdog_cs2inplay.log
timeout /t 10 /nobreak > nul
goto loop
