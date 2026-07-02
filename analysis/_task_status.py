"""Status/schedule/last-run for cleanup-candidate tasks. Laptop, read-only."""
import subprocess

CANDIDATES = ["LoLDownload", "LoLBuildModel", "PolyMaintPauseStart", "PolyMaintPauseEnd",
              "PolyMaintPauseStart_2026_05_27", "PolyMaintPauseEnd_2026_05_27",
              "PandaDownload", "PandaPipeline", "PandaFeasNotify", "Bo3Download",
              "RunBot", "PolyBotLive", "PolyPaper", "PolyBot", "PolyBotPaper",
              "DailySummary", "ReconcileBackfill", "BackupOutputs", "RotateBotLogs"]
for t in CANDIDATES:
    r = subprocess.run(["schtasks", "/query", "/tn", t, "/fo", "list", "/v"],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(f"  {t:32} MISSING"); continue
    info = {}
    for line in r.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    print(f"  {t:32} state={info.get('Scheduled Task State','?'):9} "
          f"type={info.get('Schedule Type','?'):22} lastrun={info.get('Last Run Time','?')[:16]}")
