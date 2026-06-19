@echo off
REM One-shot LoL match-history download from PandaScore (resumable).
REM Launched as scheduled task LoLDownload so it survives SSH session close.
cd /d C:\Users\matti\Desktop\prediction-market-analysis
.venv\Scripts\python.exe -u analysis\pandascore_download.py lol >> lol_download.log 2>&1
