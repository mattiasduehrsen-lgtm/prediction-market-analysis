@echo off
cd /d "C:\Users\home user\Desktop\prediction-market-analysis"

:loop
echo [%date% %time%] Starting dashboard...
.venv\Scripts\python.exe -u main.py dashboard >> dashboard.log 2>&1
echo [%date% %time%] Dashboard exited (code %errorlevel%) — restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
