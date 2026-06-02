@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysis\notify_feasibility.py >> feasibility_notify.log 2>&1
