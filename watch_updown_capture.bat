@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
set LOCKFILE=watchdog_updowncap.lock
:: self-heal stale lock — never let a leftover lock block restart (see watch_cs2_model.bat)
if exist %LOCKFILE% del /f /q %LOCKFILE%
echo %date% %time% > %LOCKFILE%
:loop
echo [%date% %time%] starting updown_book_capture >> watchdog_updowncap.log
.venv\Scripts\python.exe -u updown_book_capture.py >> watchdog_updowncap.log 2>&1
echo [%date% %time%] exited (code %errorlevel%) restart 10s >> watchdog_updowncap.log
timeout /t 10 /nobreak > nul
goto loop
