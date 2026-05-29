"""Counterfactual: would specific filters have flipped the strategy positive,
or is the edge fundamentally gone? Also tests market efficiency (WR vs price).
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "output" / "esports_fade" / "live_results.csv"

def load():
    out = []
    for r in csv.DictReader(RESULTS.open(encoding="utf-8")):
        if r["status"] not in ("WIN","LOSS","TP_SOLD","TP_LOSS"): continue
        try:
            r["_ts"]=float(r.get("ts") or 0); r["_pnl"]=float(r.get("realized_pnl") or 0)
            r["_cost"]=float(r.get("cost_usd") or 0); r["_price"]=float(r.get("price") or 0)
            r["_won"]=r["status"] in ("WIN","TP_SOLD")
        except Exception: continue
        out.append(r)
    return out

def mtype(slug):
    s=(slug or "").lower()
    if "handicap" in s or "-spread" in s: return "handicap"
    if "total" in s or "-over-" in s or "-under-" in s: return "total"
    if "-game" in s or "-map-" in s: return "map/game"
    return "moneyline"

def stat(rs, label):
    if not rs:
        print(f"  {label:<40} n=0"); return
    n=len(rs); w=sum(1 for r in rs if r["_won"])
    pnl=sum(r["_pnl"] for r in rs); cost=sum(r["_cost"] for r in rs)
    print(f"  {label:<40} n={n:>4}  WR={w/n*100:>5.1f}%  PnL ${pnl:>+8.2f}  ROI {pnl/cost*100 if cost else 0:>+6.1f}%")

rows=load()
print("="*86)
print(" MARKET EFFICIENCY TEST — does win rate track entry price? (if yes, ~no edge)")
print("="*86)
print("  Breakeven WR for a fade bought at price p is exactly p.")
print("  edge = actual_WR - entry_price. Positive edge = real alpha.\n")
buckets=[(0,0.45),(0.45,0.55),(0.55,0.65),(0.65,0.75),(0.75,0.85),(0.85,1.01)]
tot_edge_w=0; tot_n=0
for lo,hi in buckets:
    rs=[r for r in rows if lo<=r["_price"]<hi]
    if not rs: continue
    n=len(rs); w=sum(1 for r in rs if r["_won"]); wr=w/n
    avgp=sum(r["_price"] for r in rs)/n
    edge=wr-avgp
    tot_edge_w += edge*n; tot_n += n
    flag=" <-- bleeding" if edge < -0.03 else (" <-- alpha" if edge>0.03 else "")
    print(f"  price[{lo:.2f},{hi:.2f})  n={n:>4}  avg_p={avgp:.3f}  WR={wr:.3f}  "
          f"edge={edge:+.3f}{flag}")
print(f"\n  Trade-weighted average edge: {tot_edge_w/tot_n:+.4f}  "
      f"({'NO durable edge' if abs(tot_edge_w/tot_n)<0.02 else 'edge present'})")

print("\n" + "="*86)
print(" COUNTERFACTUAL FILTERS (cumulative, applied to full history)")
print("="*86)
base=rows
stat(base, "BASELINE (all trades)")
# Drop toxic wallet
f1=[r for r in base if r.get("target_wallet","")[:10]!="0x47138dc1"]
stat(f1, "- drop wallet 0x47138dc1")
# Drop map/game
f2=[r for r in f1 if mtype(r.get("fade_slug",""))!="map/game"]
stat(f2, "- also drop map/game markets")
# Drop mid-price band
f3=[r for r in f2 if not (0.55<=r["_price"]<0.65)]
stat(f3, "- also drop entry price [0.55,0.65)")
# Only series moneyline + high conf
f4=[r for r in base if mtype(r.get("fade_slug",""))=="moneyline" and r["_price"]>=0.65]
stat(f4, "ALT: only moneyline AND price>=0.65")

print("\n" + "="*86)
print(" PER-WALLET TOXICITY (wallets we fade >=4 times, sorted by PnL)")
print("="*86)
byw=defaultdict(list)
for r in rows:
    if r.get("strategy")=="fade": byw[r.get("target_wallet","")].append(r)
ranked=sorted([(w,rs) for w,rs in byw.items() if len(rs)>=4], key=lambda kv: sum(x["_pnl"] for x in kv[1]))
for w,rs in ranked[:12]:
    n=len(rs); win=sum(1 for r in rs if r["_won"]); pnl=sum(r["_pnl"] for r in rs)
    print(f"  {w[:16]}  n={n:>3}  WR={win/n*100:>5.1f}%  PnL ${pnl:>+8.2f}")

print("\n  (worst wallets above; best wallets below)")
for w,rs in ranked[-6:]:
    n=len(rs); win=sum(1 for r in rs if r["_won"]); pnl=sum(r["_pnl"] for r in rs)
    print(f"  {w[:16]}  n={n:>3}  WR={win/n*100:>5.1f}%  PnL ${pnl:>+8.2f}")

print("\n" + "="*86)
print(" LAST 3 DAYS vs FIRST 11 DAYS (has something changed?)")
print("="*86)
cut = datetime(2026,5,27,tzinfo=timezone.utc).timestamp()
early=[r for r in rows if r["_ts"]<cut]; late=[r for r in rows if r["_ts"]>=cut]
stat(early, "First 11 days (5/16-5/26)")
stat(late,  "Last 3 days (5/27-5/29)")
# Within late, efficiency
if late:
    w=sum(1 for r in late if r["_won"]); avgp=sum(r["_price"] for r in late)/len(late)
    print(f"  late-window edge: WR {w/len(late):.3f} - avg_price {avgp:.3f} = {w/len(late)-avgp:+.3f}")
