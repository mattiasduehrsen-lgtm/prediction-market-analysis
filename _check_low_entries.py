"""Check both bots for entries below $0.40."""
import csv, json, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent

print("=== Sports PAPER trades with our_entry < 0.40 ===")
sf = ROOT / "output" / "sports_fade" / "paper_trades.csv"
if sf.exists():
    low = []
    with sf.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                e = float(r.get("our_entry") or 0)
            except: continue
            if e < 0.40:
                low.append(r)
    print(f"  {len(low)} signals with entry < $0.40")
    for r in low[-10:]:
        print(f"  entry=${r['our_entry']}  outcome={r.get('our_outcome','')[:18]}  "
              f"their_price={r['their_price']}  slug={r.get('fade_slug','')[:40]}")

print()
print("=== Esports LIVE orders below $0.40 (last 24h) ===")
ef = ROOT / "output" / "esports_fade" / "live_orders.jsonl"
cutoff = time.time() - 86400
low_live = []
if ef.exists():
    with ef.open(encoding="utf-8") as f:
        for line in f:
            try: o = json.loads(line)
            except: continue
            if (o.get("ts") or 0) < cutoff: continue
            try: p = float(o.get("price") or 0)
            except: continue
            if p < 0.40 and str(o.get("side","BUY")).upper() == "BUY":
                low_live.append(o)
print(f"  {len(low_live)} LIVE BUYs in last 24h with price < $0.40")
for o in low_live[-10:]:
    print(f"  ts={o.get('ts')}  price={o.get('price')}  status={o.get('status')}  "
          f"slug={o.get('fade_slug','')[:40]}")
