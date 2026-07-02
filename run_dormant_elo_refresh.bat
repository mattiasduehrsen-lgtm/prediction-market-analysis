@echo off
REM Weekly incremental refresh for DORMANT esports (no live Polymarket H2H markets
REM yet -> Elo staleness of days is irrelevant). Incremental mode costs ~5-10
REM requests/game (vs ~250-600 for a full walk), so this whole run is <100 requests
REM of the 1,000/hr PandaScore budget. cs2/lol have their own daily refreshes.
cd /d C:\Users\matti\Desktop\prediction-market-analysis
for %%G in (dota2 valorant rl ow codmw r6siege) do (
    echo ===== %%G ===== >> dormant_refresh.log
    .venv\Scripts\python.exe -u analysis\pandascore_download.py %%G >> dormant_refresh.log 2>&1
    .venv\Scripts\python.exe -u analysis\pandascore_flatten.py %%G >> dormant_refresh.log 2>&1
    .venv\Scripts\python.exe -u analysis\build_elo.py %%G >> dormant_refresh.log 2>&1
)
echo DORMANT_REFRESH_DONE >> dormant_refresh.log
