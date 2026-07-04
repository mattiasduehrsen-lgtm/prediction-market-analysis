"""How is the v2 gate actually doing live? Fills, outcomes, maker-vs-taker,
and every skip since v1.54 (2026-07-01) with emphasis on post-v1.57 (Jul 3+)."""
import json, csv, time
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
CUT_54 = 1782000000   # ~2026-07-01 12:00Z (v1.54 turnaround live)
CUT_57 = 1782140000   # ~2026-07-03 03:30Z (v1.57 live)

print("=== A) event counts since v1.57 ===")
ev = Counter(); ev54 = Counter()
mk_reasons = Counter()
with (ROOT/"output"/"esports_fade"/"fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        ts = e.get("ts", 0)
        if ts >= CUT_54: ev54[e.get("type","?")] += 1
        if ts >= CUT_57:
            ev[e.get("type","?")] += 1
            if e.get("type") == "skip_bet_filter": mk_reasons[e.get("reason","?")] += 1
for t, c in ev.most_common(18): print(f"  {t:from28} {c}" .replace("from",""))
print("  skip_bet_filter reasons:", dict(mk_reasons))

print("\n=== B) orders since v1.54 (exec_mode, status, fill) ===")
orders = []
with (ROOT/"output"/"esports_fade"/"live_orders.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: o = json.loads(line)
        except: continue
        if o.get("ts", 0) >= CUT_54: orders.append(o)
print(f"  orders: {len(orders)}")
for o in orders:
    age_h = (time.time()-o["ts"])/3600
    print(f"   {time.strftime('%m-%d %H:%M', time.gmtime(o['ts']))} {o.get('exec_mode','pre56'):6} "
          f"{o.get('status'):9} matched={o.get('shares')} req@{o.get('requested_price')} "
          f"fill@{o.get('price')} edge={o.get('model_edge')} {str(o.get('fade_slug'))[:30]}")

print("\n=== C) resolved outcomes since v1.54 ===")
res = []
with (ROOT/"output"/"esports_fade"/"live_results.csv").open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try: ts = float(r.get("ts") or 0)
        except: continue
        if ts >= CUT_54 and float(r.get("cost_usd") or 0) > 0: res.append(r)
staked = sum(float(r["cost_usd"]) for r in res)
pnl = sum(float(r.get("realized_pnl") or 0) for r in res)
print(f"  filled positions: {len(res)} staked=${staked:.0f} realized_pnl=${pnl:+.1f}")
for r in res[-10:]:
    print(f"   {r.get('status'):9} pnl={float(r.get('realized_pnl') or 0):+6.1f} "
          f"@{r.get('price')} {str(r.get('fade_slug'))[:32]}")

print("\n=== D) daily pnl file ===")
print(" ", (ROOT/"output"/"esports_fade"/"live_daily_pnl.json").read_text()[:220])
