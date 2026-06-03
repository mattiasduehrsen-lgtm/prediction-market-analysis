@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
.venv\Scripts\python.exe -u analysisvaluate_cs2_model.py >> output\cs2_modelval.log 2>&1
