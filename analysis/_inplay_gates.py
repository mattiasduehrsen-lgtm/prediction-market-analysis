import csv, statistics as st
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
rows = list(csv.DictReader((ROOT/"output"/"cs2_inplay"/"paper_results.csv").open(encoding="utf-8")))
res = [r for r in rows if r.get("status") in ("WIN","LOSS")]
def roi(items):
    cost=sum(min(0.99,float(r["entry_price"])) for r in items)
    pnl=sum(float(r["pnl"]) for r in items if r["pnl"]!="")
    n=len(items); w=sum(1 for r in items if r["status"]=="WIN")
    return n, (w/n*100 if n else 0), (pnl/cost*100 if cost else 0)
n,wr,r = roi(res)
print(f"OVERALL: n={n} WR={wr:.0f}% ROI={r:+.1f}%")
# direction: bet_side A = front-run (back map-1 winner); B = contrarian (back loser)
fr=[x for x in res if x["bet_side"]=="A"]; co=[x for x in res if x["bet_side"]=="B"]
for lbl,items in [("front-run (back map1 winner)",fr),("contrarian (back map1 loser)",co)]:
    nn,ww,rr=roi(items); print(f"  {lbl:<32} n={nn:>3} WR={ww:.0f}% ROI={rr:+.1f}%")
# edge buckets
for thr in [0.05,0.10,0.15]:
    sub=[x for x in res if abs(float(x["edge"]))>thr]
    nn,ww,rr=roi(sub); print(f"  |edge|>{thr}: n={nn:>3} WR={ww:.0f}% ROI={rr:+.1f}%")
# latency + depth
lags=sorted(float(r["bo3_detect_lag_s"]) for r in res if r.get("bo3_detect_lag_s") not in("",None))
deps=sorted(float(r["book_depth_usd"]) for r in res if r.get("book_depth_usd") not in("",None))
print(f"\nlatency: median={st.median(lags):.0f}s  under180={sum(1 for x in lags if x<=180)}/{len(lags)} ({sum(1 for x in lags if x<=180)/len(lags)*100:.0f}%)")
print(f"depth: median=${st.median(deps):.0f}  >= $50: {sum(1 for x in deps if x>=50)}/{len(deps)} ({sum(1 for x in deps if x>=50)/len(deps)*100:.0f}%)")
# fill realism: depth >= our $10 bet (could we fill $10 at the ask?)
fillable=sum(1 for r in res if r.get("book_depth_usd") not in("",None) and float(r["book_depth_usd"])>=10)
print(f"fill realism (depth>=$10 bet): {fillable}/{len(res)} ({fillable/len(res)*100:.0f}%)")
