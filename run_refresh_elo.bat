@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysis\refresh_elo.py >> cs2_elo_refresh.log 2>&1
