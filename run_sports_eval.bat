@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe analysis\evaluate_sports_paper.py >> output\sports_fade\eval.log 2>&1
