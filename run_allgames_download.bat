@echo off
REM v1.55 net-widening: pull full match history + build validated Elo for every
REM esport PandaScore covers, so a model is READY the moment Polymarket/GRID lists
REM H2H markets for it. Resumable + rate-limited; safe to re-run. Sequential on
REM purpose (shared 1000 req/hr budget).
cd /d C:\Users\matti\Desktop\prediction-market-analysis
for %%G in (dota2 valorant rl ow codmw r6siege) do (
    echo ===== %%G ===== >> allgames_download.log
    .venv\Scripts\python.exe -u analysis\pandascore_download.py %%G >> allgames_download.log 2>&1
    .venv\Scripts\python.exe -u analysis\pandascore_flatten.py %%G >> allgames_download.log 2>&1
    .venv\Scripts\python.exe -u analysis\build_elo.py %%G >> allgames_download.log 2>&1
)
echo ALLGAMES_DONE >> allgames_download.log
