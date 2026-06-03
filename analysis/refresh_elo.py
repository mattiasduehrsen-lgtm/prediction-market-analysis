"""Keep the CS2 Elo ratings current: pull recently-finished matches from
PandaScore, append new ones, re-flatten, and rebuild Elo. Run hourly.
"""
from __future__ import annotations
import os, json, time, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TOKEN = os.environ["PANDASCORE_TOKEN"].strip()
RAW = ROOT / "cowork_snapshot" / "gamedata" / "pandascore" / "cs2_matches_raw.jsonl"
PY = ROOT / ".venv" / "Scripts" / "python.exe"
S = requests.Session()
S.headers.update({"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})

def load_seen():
    seen = set()
    if RAW.exists():
        with RAW.open(encoding="utf-8") as fh:
            for line in fh:
                try: seen.add(json.loads(line)["id"])
                except Exception: pass
    return seen

def main():
    seen = load_seen()
    since = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fh = RAW.open("a", encoding="utf-8")
    new = 0; page = 1
    while True:
        try:
            r = S.get("https://api.pandascore.co/csgo/matches/past",
                      params={"range[begin_at]": f"{since},{now}", "per_page": 100,
                              "page": page, "sort": "begin_at"}, timeout=30)
        except Exception as e:
            print(f"refresh req error: {e}"); break
        if r.status_code != 200:
            print(f"[{r.status_code}] {r.text[:120]}"); break
        data = r.json()
        if not data: break
        for m in data:
            if m.get("id") in seen: continue
            seen.add(m["id"]); fh.write(json.dumps(m) + "\n"); new += 1
        fh.flush()
        if len(data) < 100: break
        page += 1
        time.sleep(1.2)
    fh.close()
    print(f"[refresh-elo] +{new} new matches")
    # rebuild flatten + elo
    subprocess.run([str(PY), str(ROOT / "analysis" / "pandascore_flatten.py")], cwd=str(ROOT))
    subprocess.run([str(PY), str(ROOT / "analysis" / "build_elo.py")], cwd=str(ROOT))
    print("[refresh-elo] Elo rebuilt")

if __name__ == "__main__":
    main()
