@echo off
REM Full autonomous pipeline: download CS2 data, then run the feasibility chain.
REM Download is resumable (skips already-saved matches), so restarting is safe.
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
echo ==== pipeline start %date% %time% ==== >> pipeline.log
.venv\Scripts\python.exe -u analysis\pandascore_download.py     >> pipeline.log 2>&1
echo ---- download done, starting analysis %date% %time% ---- >> pipeline.log
.venv\Scripts\python.exe -u analysis\pandascore_flatten.py      >> pipeline.log 2>&1
.venv\Scripts\python.exe -u analysis\polymarket_cs2_markets.py  >> pipeline.log 2>&1
.venv\Scripts\python.exe -u analysis\build_elo.py               >> pipeline.log 2>&1
.venv\Scripts\python.exe -u analysis\prematch_prices.py         >> pipeline.log 2>&1
.venv\Scripts\python.exe -u analysis\feasibility.py             >> pipeline.log 2>&1
echo ==== pipeline done %date% %time% ==== >> pipeline.log
