@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe analysis\evaluate_sports_live.py >> output\sports_fade\eval_live.log 2>&1
