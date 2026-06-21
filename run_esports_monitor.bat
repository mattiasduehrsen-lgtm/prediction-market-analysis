@echo off
REM Daily esports market monitor — detects the Polymarket x GRID expansion
REM (new games, LoL head-to-head markets, liquidity arriving) and alerts.
cd /d C:\Users\matti\Desktop\prediction-market-analysis
.venv\Scripts\python.exe -u analysis\esports_market_monitor.py >> esports_monitor.log 2>&1
