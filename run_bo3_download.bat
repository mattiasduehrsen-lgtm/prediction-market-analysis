@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysis\bo3_download.py >> bo3_download.log 2>&1
