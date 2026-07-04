"""Clean PnL since the REAL v1.57 activation (2026-07-03 13:00Z), split
legit-series vs prop-bug fills."""
import csv, re
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
CUT = datetime(2026, 7, 3, 13, 0, tzinfo=timezone.utc).timestamp()
PROP = re.compile(r"-game\d+|-game-|-map-?\d*\b|-map-|handicap|kill|first-|total", re.I)
rows = []
with (ROOT/"output"/"esports_fade"/"live_results.csv").open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        try: ts = float(r.get("ts") or 0)
        except: continue
        if ts >= CUT and float(r.get("cost_usd") or 0) > 0:
            rows.append(r)
def show(label, items):
    st = sum(float(r["cost_usd"]) for r in items)
    pnl = sum(float(r.get("realized_pnl") or 0) for r in items)
    res = [r for r in items if r.get("status") in ("WIN","LOSS")]
    w = sum(1 for r in res if r["status"]=="WIN")
    print(f"{label:22} fills={len(items):2d} staked=${st:5.0f} | resolved={len(res)} W-L={w}-{len(res)-w} realized=${pnl:+.1f}")
    for r in items:
        print(f"    {r.get('status'):10} pnl={float(r.get('realized_pnl') or 0):+6.1f} @{r.get('price')} {str(r.get('fade_slug'))[:40]}")
legit = [r for r in rows if not PROP.search(r.get("fade_slug") or "")]
prop  = [r for r in rows if PROP.search(r.get("fade_slug") or "")]
show("LEGIT series fades", legit)
show("PROP-BUG fills", prop)
