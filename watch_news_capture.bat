@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
set LOCKFILE=watchdog_newscap.lock
:: self-heal stale lock — never let a leftover lock block restart
if exist %LOCKFILE% del /f /q %LOCKFILE%
echo %date% %time% > %LOCKFILE%
:loop
echo [%date% %time%] starting news_capture >> watchdog_newscap.log
.venv\Scripts\python.exe -u news_capture.py >> watchdog_newscap.log 2>&1
echo [%date% %time%] exited (code %errorlevel%) restart 10s >> watchdog_newscap.log
timeout /t 10 /nobreak > nul
goto loop
