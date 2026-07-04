"""LIVE calibration referee: join shadow_compare events (both Elo + v2 probs on
real fade signals) to market resolutions -> whose probabilities were honest?"""
import json
from pathlib import Path
import pandas as pd
ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
ev = []
with (ROOT/"output"/"esports_fade"/"fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        if '"shadow_compare"' not in line: continue
        try: e = json.loads(line)
        except: continue
        if e.get("type") == "shadow_compare" and e.get("shadow_ok"):
            ev.append(e)
print(f"shadow_compare events with both probs: {len(ev)}")
res = pd.read_parquet(ROOT/"cowork_snapshot"/"esports"/"resolutions.parquet")
res = res[res.winning_outcome.notna()][["slug","winning_outcome"]].drop_duplicates("slug")
win = dict(zip(res.slug, res.winning_outcome))
rows = []
seen = set()
for e in ev:
    k = (e.get("slug"), e.get("our_outcome"))
    if k in seen: continue
    seen.add(k)
    w = win.get(e.get("slug"))
    if not w: continue
    won = int(str(w).strip().lower() == str(e.get("our_outcome")).strip().lower())
    rows.append({"slug": e["slug"], "won": won, "elo_p": e.get("elo_p"),
                 "v2_p": e.get("shadow_p"), "entry": e.get("our_entry")})
df = pd.DataFrame(rows).dropna()
print(f"resolved + scored: {len(df)}")
for col in ("elo_p", "v2_p", "entry"):
    b = ((df[col]-df.won)**2).mean()
    print(f"  {col:6} Brier={b:.4f}  (market price as prob = 'entry' row)")
hi = df[df.v2_p >= 0.65]
print(f"\n  v2 high-confidence (p>=0.65): n={len(hi)} predicted~{hi.v2_p.mean():.2f} actual WR={hi.won.mean():.2f}")
hi_e = df[df.elo_p >= 0.65]
print(f"  Elo high-confidence (p>=0.65): n={len(hi_e)} predicted~{hi_e.elo_p.mean():.2f} actual WR={hi_e.won.mean():.2f}")
