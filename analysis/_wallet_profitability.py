"""Which target wallets did we fade most profitably, and would PINNING the
profitable ones (instead of refreshing them out) actually be profitable?

The honest test is train/test by TIME:
  1. Split our live fade history at a cutoff.
  2. Rank wallets by how profitable fading them was in TRAIN.
  3. Take the wallets that were profitable in TRAIN.
  4. Measure how those SAME wallets performed in TEST (out-of-sample).
If pinned-winners make money in TEST, persistence is real and pinning helps.
If not, the per-wallet "edge" was just noise (don't pin).
"""
from __future__ import annotations
import csv
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import statistics as st

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "output" / "esports_fade" / "live_results.csv"

rows = []
for r in csv.DictReader(RES.open(encoding="utf-8")):
    if r["status"] not in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS"):
        continue
    if r.get("strategy") != "fade":
        continue
    try:
        rows.append({
            "ts": float(r.get("ts") or 0),
            "wallet": (r.get("target_wallet") or "").lower(),
            "pnl": float(r.get("realized_pnl") or 0),
            "cost": float(r.get("cost_usd") or 0),
            "won": r["status"] in ("WIN", "TP_SOLD"),
        })
    except Exception:
        continue
rows.sort(key=lambda x: x["ts"])
print(f"resolved fade trades: {len(rows)}")
if not rows:
    raise SystemExit

def stats(rs):
    n=len(rs); w=sum(x["won"] for x in rs)
    pnl=sum(x["pnl"] for x in rs); cost=sum(x["cost"] for x in rs)
    return n, w, pnl, cost, (pnl/cost*100 if cost else 0)

# ── 1. Lifetime per-wallet leaderboard ──────────────────────────────────
print("\n" + "="*78)
print(" PER-WALLET FADE PROFITABILITY (lifetime, wallets we faded >=3x)")
print("="*78)
byw = defaultdict(list)
for r in rows: byw[r["wallet"]].append(r)
ranked = sorted(byw.items(), key=lambda kv: -sum(x["pnl"] for x in kv[1]))
print(f"  {'wallet':<16}{'n':>4}{'WR':>7}{'PnL':>10}{'ROI':>8}")
shown=[kv for kv in ranked if len(kv[1])>=3]
for w,rs in shown[:12]:
    n,win,pnl,cost,roi=stats(rs)
    print(f"  {w[:14]:<16}{n:>4}{win/n*100:>6.0f}%{pnl:>+10.2f}{roi:>+7.0f}%")
print("  ...")
for w,rs in shown[-6:]:
    n,win,pnl,cost,roi=stats(rs)
    print(f"  {w[:14]:<16}{n:>4}{win/n*100:>6.0f}%{pnl:>+10.2f}{roi:>+7.0f}%")
n_pos=sum(1 for w,rs in byw.items() if sum(x['pnl'] for x in rs)>0)
print(f"\n  wallets faded: {len(byw)}  |  profitable: {n_pos}  |  unprofitable: {len(byw)-n_pos}")

# ── 2. TRAIN/TEST by time ───────────────────────────────────────────────
cut_idx = int(len(rows)*0.6)
cut_ts = rows[cut_idx]["ts"]
train=[r for r in rows if r["ts"]<cut_ts]
test =[r for r in rows if r["ts"]>=cut_ts]
print("\n" + "="*78)
print(f" TRAIN/TEST SPLIT  (train={len(train)} trades, test={len(test)} trades)")
print(f"   cut at {datetime.fromtimestamp(cut_ts,tz=timezone.utc).isoformat()}")
print("="*78)

tr_by=defaultdict(list)
for r in train: tr_by[r["wallet"]].append(r)
te_by=defaultdict(list)
for r in test: te_by[r["wallet"]].append(r)

# "Pinned winners": wallets profitable in TRAIN (require >=2 train fades)
pinned = {w for w,rs in tr_by.items()
          if len(rs)>=2 and sum(x["pnl"] for x in rs)>0}
print(f"\n  wallets profitable in TRAIN (>=2 fades): {len(pinned)}")

# How did those SAME wallets do in TEST?
test_pinned = [r for r in test if r["wallet"] in pinned]
test_all    = test
test_other  = [r for r in test if r["wallet"] not in pinned]

def line(label, rs):
    if not rs:
        print(f"  {label:<34} no trades"); return
    n,w,pnl,cost,roi=stats(rs)
    print(f"  {label:<34} n={n:>4}  WR={w/n*100:>5.0f}%  PnL ${pnl:>+8.2f}  ROI {roi:>+6.1f}%")

print("\n  OUT-OF-SAMPLE (test window):")
line("fade ONLY train-profitable wallets", test_pinned)
line("fade EVERYONE (baseline)", test_all)
line("fade the rest (non-pinned)", test_other)

# ── 3. Persistence correlation ──────────────────────────────────────────
common=[w for w in tr_by if w in te_by and len(tr_by[w])>=2 and len(te_by[w])>=2]
if len(common)>=4:
    tr_roi=[stats(tr_by[w])[4] for w in common]
    te_roi=[stats(te_by[w])[4] for w in common]
    try:
        import statistics
        # Pearson
        mtr=statistics.mean(tr_roi); mte=statistics.mean(te_roi)
        cov=sum((a-mtr)*(b-mte) for a,b in zip(tr_roi,te_roi))/len(common)
        sd=statistics.pstdev(tr_roi)*statistics.pstdev(te_roi)
        corr=cov/sd if sd else 0
        print(f"\n  wallet ROI persistence (train vs test ROI), n={len(common)} wallets:")
        print(f"    correlation = {corr:+.3f}  "
              f"({'losers stay losers (pinning helps)' if corr>0.15 else 'no/!inverted persistence (pinning is noise)'})")
    except Exception as e:
        print(f"  persistence calc failed: {e}")
else:
    print(f"\n  too few wallets faded >=2x in BOTH windows ({len(common)}) for a persistence stat")

print("\n  NOTE: per-wallet samples are small; treat as directional, not precise.")
