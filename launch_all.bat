@echo off
cd /d "C:\Users\home user\Desktop\prediction-market-analysis"
echo Killing any existing python processes...
taskkill /F /IM python.exe 2>nul
timeout /t 2 /nobreak >nul

echo Starting bot watchdog...
start "BTC5mBot" /MIN cmd /k watchdog_bot.bat

echo Starting dashboard watchdog...
start "BTC5mDashboard" /MIN cmd /k watchdog_dashboard.bat

echo Both watchdogs launched.
