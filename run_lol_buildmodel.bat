@echo off
REM After the LoL download completes: flatten raw -> parquet, then build Elo
REM (build_elo prints the validation gate: accuracy / Brier / log-loss / calibration).
cd /d C:\Users\matti\Desktop\prediction-market-analysis
.venv\Scripts\python.exe -u analysis\pandascore_flatten.py lol >> lol_build.log 2>&1
.venv\Scripts\python.exe -u analysis\build_elo.py lol >> lol_build.log 2>&1
echo BUILD_DONE >> lol_build.log
