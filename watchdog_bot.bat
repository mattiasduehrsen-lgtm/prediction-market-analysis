@echo off
cd /d "C:\Users\home user\Desktop\prediction-market-analysis"

:loop
echo [%date% %time%] Starting BTC 5m bot...
.venv\Scripts\python.exe -u main.py btc-5m-loop
echo [%date% %time%] Bot exited (code %errorlevel%) — restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
