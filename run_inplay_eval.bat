@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysis\evaluate_inplay.py >> output\cs2_inplay\eval.log 2>&1
