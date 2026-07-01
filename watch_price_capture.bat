@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
set LOCKFILE=watchdog_pricecap.lock
:: self-heal stale lock — never let a leftover lock block restart (see watch_cs2_model.bat)
if exist %LOCKFILE% del /f /q %LOCKFILE%
echo %date% %time% > %LOCKFILE%
:loop
echo [%date% %time%] starting price_capture >> watchdog_pricecap.log
.venv\Scripts\python.exe -u price_capture.py >> watchdog_pricecap.log 2>&1
echo [%date% %time%] exited (code %errorlevel%) restart 10s >> watchdog_pricecap.log
timeout /t 10 /nobreak > nul
goto loop
