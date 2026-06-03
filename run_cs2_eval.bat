@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysis\evaluate_cs2_model.py >> output\cs2_model\eval.log 2>&1
