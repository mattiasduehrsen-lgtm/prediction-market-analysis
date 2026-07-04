@echo off
REM Keep the LoL Elo model current: incremental match download (resumable/dedup),
REM flatten, rebuild Elo. The fade bot hot-reloads lol_*.parquet on mtime change.
cd /d C:\Users\matti\Desktop\prediction-market-analysis
.venv\Scripts\python.exe -u analysis\pandascore_download.py lol >> lol_elo_refresh.log 2>&1
.venv\Scripts\python.exe -u analysis\pandascore_flatten.py lol >> lol_elo_refresh.log 2>&1
.venv\Scripts\python.exe -u analysis\build_elo.py lol >> lol_elo_refresh.log 2>&1
echo REFRESH_DONE >> lol_elo_refresh.log
REM v1.58: tier index rebuilt DAILY (was weekly-only) — the build live-fetches the
REM 500 newest bo3 matches, so upcoming-match tiers stay fresh instead of going
REM stale mid-week ("tier unknown" was skipping legitimate fades).
.venv\Scripts\python.exe -u analysis\build_tier_index.py >> lol_elo_refresh.log 2>&1
