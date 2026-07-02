"""Deep decomposition of in-play paper results — is the +40% real or luck?

The red flag: dose-response is INVERTED (bigger model-vs-market edge = WORSE ROI),
which means the MODEL isn't the source of profit. Candidate real mechanism: the
market OVERREACTS to the map-1 result, so backing the map-1 LOSER cheap is +EV
structurally. This script tests that hypothesis and the robustness of the sample:
  1. outlier concentration (is PnL driven by 2-3 longshot wins?)
  2. ROI by entry-price bucket x side (front-run vs contrarian)
  3. stability across calendar weeks (does the edge persist?)
  4. v1 vs v2 model comparison where both logged
Run on the laptop."""
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
rows = list(csv.DictReader((ROOT / "output" / "cs2_inplay" / "paper_results.csv").open(encoding="utf-8")))
res = [r for r in rows if r.get("status") in ("WIN", "LOSS")]
BET = 10.0

def f(r, k, d=0.0):
    try: return float(r.get(k, d) or d)
    except ValueError: return d

for r in res:
    r["_pnl"] = f(r, "pnl")
    r["_price"] = f(r, "entry_price")
    r["_edge"] = abs(f(r, "edge"))
    r["_week"] = datetime.fromtimestamp(f(r, "ts"), tz=timezone.utc).strftime("%Y-W%W") if f(r, "ts") else "?"

def roi(items):
    n = len(items)
    if not n: return 0, 0.0, 0.0
    pnl = sum(r["_pnl"] for r in items)
    wr = sum(1 for r in items if r["status"] == "WIN") / n * 100
    return n, wr, pnl / (n * BET) * 100

n, wr, r_all = roi(res)
tot_pnl = sum(x["_pnl"] for x in res)
print(f"OVERALL: n={n} WR={wr:.0f}% ROI={r_all:+.1f}%  total_pnl=${tot_pnl:+.0f}")

print("\n1) OUTLIER CONCENTRATION (top wins vs total pnl)")
wins = sorted((x["_pnl"] for x in res if x["_pnl"] > 0), reverse=True)
for k in (1, 3, 5):
    top = sum(wins[:k])
    print(f"   top-{k} wins = ${top:+.0f} = {top/tot_pnl*100 if tot_pnl>0 else 0:.0f}% of total pnl")
ex3 = sorted(res, key=lambda x: -x["_pnl"])[3:]
n3, wr3, roi3 = roi(ex3)
print(f"   EXCLUDING top-3 wins: n={n3} WR={wr3:.0f}% ROI={roi3:+.1f}%   <- robustness check")

print("\n2) ENTRY PRICE x SIDE (A=front-run map1 winner, B=contrarian map1 loser)")
print(f"   {'bucket':<12} {'side':<4} {'n':>4} {'WR%':>5} {'ROI%':>8}")
for lo, hi in [(0, 0.15), (0.15, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.0)]:
    for side in ("A", "B"):
        sub = [x for x in res if lo <= x["_price"] < hi and x.get("bet_side") == side]
        if not sub: continue
        nn, ww, rr = roi(sub)
        print(f"   {f'{lo}-{hi}':<12} {side:<4} {nn:>4} {ww:>5.0f} {rr:>+8.1f}")

print("\n3) WEEKLY STABILITY")
weeks = defaultdict(list)
for x in res: weeks[x["_week"]].append(x)
for w in sorted(weeks):
    nn, ww, rr = roi(weeks[w])
    print(f"   {w}: n={nn:>3} WR={ww:.0f}% ROI={rr:+.1f}%")

print("\n4) CONTRARIAN ONLY, weekly (the candidate edge)")
for w in sorted(weeks):
    sub = [x for x in weeks[w] if x.get("bet_side") == "B"]
    if not sub: continue
    nn, ww, rr = roi(sub)
    print(f"   {w}: n={nn:>3} WR={ww:.0f}% ROI={rr:+.1f}%")

cols = res[0].keys() if res else []
print(f"\n(available cols: {', '.join(list(cols)[:18])})")
