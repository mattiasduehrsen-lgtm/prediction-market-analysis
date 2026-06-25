@echo off
REM Rebuild the esports_model serving state (team ratings + h2h) from the latest
REM PandaScore matches, so the shadow predictor stays current. build_state re-runs
REM the walk-forward from {game}_matches.parquet (refreshed by CS2EloRefresh /
REM LoLEloRefresh), so no separate feature build or model retrain is needed.
REM The running bot picks up the fresh state on its next restart.
cd /d C:\Users\matti\Desktop\prediction-market-analysis
.venv\Scripts\python.exe -u esports_model\src\build_state.py >> esports_model_state.log 2>&1
echo STATE_REBUILD_DONE >> esports_model_state.log
