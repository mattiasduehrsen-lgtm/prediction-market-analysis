"""The 5 losing v1.57 fades: v2's prob vs Elo's prob on each (shadow_compare),
plus the live edge distribution vs what the backtest expected."""
import json
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
CUT = datetime(2026, 7, 3, 13, 0, tzinfo=timezone.utc).timestamp()
LOSERS = ("cs2-ge3-pcy-2026-07-03", "cs2-mw-mag-2026-07-03", "cs2-mibra-vexa1-2026-07-04",
          "cs2-paina-bsta-2026-07-04")
sc, mp = [], []
with (ROOT/"output"/"esports_fade"/"fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        if '"shadow_compare"' not in line and '"model_filter_pass"' not in line:
            continue
        try: e = json.loads(line)
        except: continue
        if e.get("ts", 0) < CUT: continue
        if e.get("type") == "shadow_compare" and e.get("slug") in LOSERS: sc.append(e)
        if e.get("type") == "model_filter_pass": mp.append(e)
print("=== the losing markets: v2 (primary) vs Elo (logged alongside) ===")
seen = set()
for e in sc:
    k = (e.get("slug"), e.get("our_outcome"))
    if k in seen: continue
    seen.add(k)
    print(f"  {e['slug'][:30]:30} our={str(e.get('our_outcome'))[:14]:14} entry={e.get('our_entry')} "
          f"| Elo p={e.get('elo_p')} edge={e.get('elo_edge')} | v2 p={e.get('shadow_p')} edge={e.get('shadow_edge')}")
print(f"\n=== live edge distribution on ALL {len(mp)} gate passes since v1.57 ===")
edges = sorted(float(e.get("model_edge") or 0) for e in mp)
import statistics as st
print(f"  n={len(edges)} median={st.median(edges):.3f} p25={edges[len(edges)//4]:.3f} p75={edges[3*len(edges)//4]:.3f} max={max(edges):.3f}")
print(f"  (backtest expectation: edge>=0.20 was only ~13% of markets; median gate-pass edge ~0.13)")
by_model = {}
for e in mp: by_model.setdefault(e.get("model"), []).append(float(e.get("model_edge") or 0))
for m, v in by_model.items(): print(f"  model={m}: n={len(v)} median_edge={st.median(v):.3f}")
