@echo off
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
echo ==== bo3 pipeline start %date% %time% ==== >> bo3_pipeline.log
.venv\Scripts\python.exe -u analysis\bo3_download.py     >> bo3_pipeline.log 2>&1
.venv\Scripts\python.exe -u analysis\build_map_model.py  >> bo3_pipeline.log 2>&1
.venv\Scripts\python.exe -u analysis\map_feasibility.py  >> bo3_pipeline.log 2>&1
echo ==== bo3 pipeline done %date% %time% ==== >> bo3_pipeline.log
