import json, time
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
# 1. skip-reason distribution from the paper bot's events
ev = ROOT/"output"/"cs2_model"/"events.jsonl"
reasons = Counter()
if ev.exists():
    for line in ev.open(encoding="utf-8"):
        try: e = json.loads(line)
        except: continue
        t = e.get("type","?")
        if t == "skip": reasons[f"skip:{e.get('reason','?')}"] += 1
        else: reasons[t] += 1
print("=== paper bot event reasons ===")
for k,c in reasons.most_common(): print(f"  {c:>5}  {k}")
# 2. upcoming CS2 markets in various windows right now
m = pd.read_parquet(ROOT/"cowork_snapshot"/"esports"/"clob_esports_markets.parquet",
                    columns=["slug","question","game_start","closed"])
m = m[m["slug"].fillna("").str.startswith("cs2-")].copy()
m["game_start"] = pd.to_datetime(m["game_start"], errors="coerce", utc=True)
now = datetime.now(timezone.utc)
openm = m[~m["closed"].fillna(False)]
for label, mins in [("next 15 min",15),("next 1h",60),("next 6h",360),("next 24h",1440)]:
    w = openm[(openm["game_start"]>now) & (openm["game_start"]<=now+timedelta(minutes=mins))]
    print(f"  upcoming open CS2 markets {label}: {len(w)}")
# show the soonest upcoming
soon = openm[openm["game_start"]>now].sort_values("game_start").head(6)
print("\n=== soonest upcoming CS2 markets ===")
for r in soon.itertuples(index=False):
    mins = (r.game_start - now).total_seconds()/60
    print(f"  in {mins:6.0f} min  {str(r.question)[:55]}")
