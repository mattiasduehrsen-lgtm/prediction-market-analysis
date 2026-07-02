"""Daily prop-edge scanner — turns price_capture data into the prop/arb backtest.

For every captured market, take its LAST quote before game_start, join the resolved
winner (resolutions.parquet), and score by market class (series / map-winner /
totals / handicaps / kills / first-blood). Two questions, answered with REAL quotes
(not the fill-price fantasy that inflated the old wallet backtest):
  1. Are prop quotes well-calibrated, or is there a soft class (edge for a model)?
  2. Consistency: does buying EVERY cheap side profit anywhere (structural bias)?
Accumulates as price_capture runs; run daily (task PropEdgeScan). Output: report +
output/price_capture/prop_edge_report.json
"""
import json, re, glob
from collections import defaultdict
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
CAP = ROOT / "output" / "price_capture"
MK = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
RES = ROOT / "cowork_snapshot" / "esports" / "resolutions.parquet"

def market_class(slug):
    s = (slug or "").lower()
    if "kill" in s: return "kills"
    if "first-blood" in s or "first-tower" in s: return "firsts"
    if "handicap" in s: return "handicap"
    if "total" in s: return "totals"
    if re.search(r"-game\d|-map-?\d", s): return "map_winner"
    return "series"

# 1) last pre-start quote per (cid, outcome)
rows = []
for f in sorted(glob.glob(str(CAP / "prices_*.jsonl"))):
    with open(f, encoding="utf-8") as fh:
        for line in fh:
            try: rows.append(json.loads(line))
            except Exception: pass
if not rows:
    print("no captured prices yet"); raise SystemExit
q = pd.DataFrame(rows)
q["gs"] = pd.to_datetime(q["gs"], errors="coerce", utc=True)
q["ts_dt"] = pd.to_datetime(q["ts"], unit="s", utc=True)
pre = q[q["ts_dt"] < q["gs"]].sort_values("ts")
last = pre.groupby("cid").last().reset_index()
print(f"captured quotes: {len(q):,} rows | markets with a pre-start quote: {len(last):,}")

# 2) join resolution (winner outcome per cid)
res = pd.read_parquet(RES)
wcol = next((c for c in ("winner", "winner_outcome", "outcome") if c in res.columns), None)
ccol = next((c for c in ("condition_id", "cid") if c in res.columns), None)
if not wcol or not ccol:
    print(f"resolutions schema unexpected: {list(res.columns)}"); raise SystemExit
res = res[[ccol, wcol]].dropna().rename(columns={ccol: "cid", wcol: "winner"})
j = last.merge(res, on="cid", how="inner")
j = j[(j["ask"].notna()) & (j["bid"].notna()) & (j["ask"] > 0) & (j["ask"] < 1)]
j["won"] = (j["outcome"].astype(str).str.strip().str.lower()
            == j["winner"].astype(str).str.strip().str.lower()).astype(int)
j["cls"] = j["slug"].map(market_class)
print(f"resolved + quoted markets: {len(j):,}")

# 3) per-class calibration + cheap-side test (buy the quoted token at ask, 2c fee)
out = {}
print(f"\n{'class':<12} {'n':>5} {'avg_ask':>8} {'win%':>6} {'roi_buy_ask%':>12}")
for cls, g in j.groupby("cls"):
    n = len(g)
    if n < 5: continue
    fee = 0.02
    rets = [(1.0 / min(0.99, a + fee) - 1.0) if w else -1.0 for a, w in zip(g["ask"], g["won"])]
    roi = sum(rets) / n * 100
    line = {"n": int(n), "avg_ask": round(float(g['ask'].mean()), 3),
            "win_pct": round(float(g['won'].mean() * 100), 1), "roi_buy_ask_pct": round(roi, 1)}
    out[cls] = line
    print(f"{cls:<12} {n:>5} {line['avg_ask']:>8} {line['win_pct']:>6} {line['roi_buy_ask_pct']:>12}")

(CAP / "prop_edge_report.json").write_text(json.dumps(out, indent=2))
print("\n(negative roi everywhere = quotes efficient at ask; a persistently positive")
print(" class = model target / structural bias. Sample grows daily with price_capture.)")
