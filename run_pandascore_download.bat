@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysis\pandascore_download.py >> pandascore_download.log 2>&1
