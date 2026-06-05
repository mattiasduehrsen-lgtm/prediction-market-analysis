@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysis\notify_map.py >> map_notify.log 2>&1
