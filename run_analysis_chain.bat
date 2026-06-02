@echo off
REM Post-download analysis chain for the CS2 model feasibility study.
cd /d "C:\Users\matti\Desktop\prediction-market-analysis"
echo ==== chain start %date% %time% ==== >> analysis_chain.log
.venv\Scripts\python.exe -u analysis\pandascore_flatten.py        >> analysis_chain.log 2>&1
.venv\Scripts\python.exe -u analysis\polymarket_cs2_markets.py    >> analysis_chain.log 2>&1
.venv\Scripts\python.exe -u analysis\build_elo.py                 >> analysis_chain.log 2>&1
.venv\Scripts\python.exe -u analysis\prematch_prices.py           >> analysis_chain.log 2>&1
.venv\Scripts\python.exe -u analysis\feasibility.py               >> analysis_chain.log 2>&1
echo ==== chain done %date% %time% ==== >> analysis_chain.log
