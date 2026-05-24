"""Generate a plain-text Notepad-friendly report of top losing wallets.

Pulls from:
  - cowork_snapshot/sports/fade_targets.json   (NHL+NBA+MLB+Tennis+Soccer)
  - cowork_snapshot/esports/fade_targets.json  (CS2+LoL)
  - per-sport losing_wallets.parquet files     (for detail breakdowns)

Output: top_wallets.txt in repo root.
"""
from __future__ import annotations
import json
import datetime as dt
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
COWORK = ROOT / "cowork_snapshot"
OUT = ROOT / "top_wallets.txt"

lines = []
def w(s=""):
    lines.append(s)

# Build per-wallet aggregate
wallet_data = defaultdict(lambda: {
    "pnl": 0.0, "trades": 0, "sports": set()
})

# Per-sport data
SPORTS = ["nhl", "nba", "mlb", "tennis", "soccer"]
for sport in SPORTS:
    f = COWORK / f"{sport}_recon" / "losing_wallets.parquet"
    if not f.exists(): continue
    df = pd.read_parquet(f)
    for w_addr, row in df.iterrows():
        wl = w_addr.lower()
        wallet_data[wl]["pnl"] += float(row["pnl"])
        wallet_data[wl]["trades"] += int(row["trades"])
        wallet_data[wl]["sports"].add(sport)

# Also load esports
es_targets_path = COWORK / "esports" / "fade_targets.json"
if es_targets_path.exists():
    es_data = json.loads(es_targets_path.read_text(encoding="utf-8"))
    es_meta = es_data.get("target_meta", [])
    for m in es_meta:
        wl = m.get("proxyWallet","").lower() if "proxyWallet" in m else None
        if not wl: continue
        wallet_data[wl]["pnl"]    += float(m.get("pnl", 0))
        wallet_data[wl]["trades"] += int(m.get("trades", 0))
        wallet_data[wl]["sports"].add("esports")

# Sort by PnL ascending (biggest losers first)
sorted_w = sorted(wallet_data.items(), key=lambda x: x[1]["pnl"])

# Build report
w("=" * 78)
w("        POLYMARKET TOP LOSING WALLETS — FADE TARGETS")
w(f"        Generated: {dt.datetime.now().isoformat(timespec='seconds')}")
w(f"        Window: trailing 14 days of trading activity")
w("=" * 78)
w()
w(f"Total unique losing wallets (across all categories):  {len(wallet_data):,}")
w()
w("Source files:")
w(f"  Sports recons: {COWORK}/{{nhl,nba,mlb,tennis,soccer}}_recon/losing_wallets.parquet")
w(f"  Esports list:  {COWORK}/esports/fade_targets.json")
w()
w()

# Top 50 by absolute loss
w("=" * 78)
w(" TOP 50 BIGGEST LOSERS (sorted by total PnL across categories)")
w("=" * 78)
w()
w(f"{'#':>3}  {'wallet':<44}  {'trades':>7}  {'pnl_usd':>12}  categories")
w("-" * 100)
for i, (w_addr, info) in enumerate(sorted_w[:50], 1):
    cats = ",".join(sorted(info["sports"]))
    w(f"{i:>3}  {w_addr:<44}  {info['trades']:>7}  ${info['pnl']:>10,.0f}  {cats}")

w()
w()

# Multi-category losers (best fade targets — predictable across sports)
multi = [(addr, info) for addr, info in sorted_w if len(info["sports"]) >= 2]
multi_3plus = [(addr, info) for addr, info in sorted_w if len(info["sports"]) >= 3]

w("=" * 78)
w(f" OMNI-LOSERS — wallets losing in 2+ categories  ({len(multi)} total)")
w(" These are the predictable ones — bad bettors regardless of sport.")
w("=" * 78)
w()
w(f"{'#':>3}  {'wallet':<44}  {'trades':>7}  {'pnl_usd':>12}  categories")
w("-" * 100)
for i, (w_addr, info) in enumerate(multi[:30], 1):
    cats = ",".join(sorted(info["sports"]))
    w(f"{i:>3}  {w_addr:<44}  {info['trades']:>7}  ${info['pnl']:>10,.0f}  {cats}")
w()

if multi_3plus:
    w("=" * 78)
    w(f" TRIPLE-CATEGORY OMNI-LOSERS — losing in 3+ categories  ({len(multi_3plus)} total)")
    w(" The most valuable fade targets — broad systematic bad-betting behavior.")
    w("=" * 78)
    w()
    w(f"{'#':>3}  {'wallet':<44}  {'trades':>7}  {'pnl_usd':>12}  categories")
    w("-" * 100)
    for i, (w_addr, info) in enumerate(multi_3plus, 1):
        cats = ",".join(sorted(info["sports"]))
        w(f"{i:>3}  {w_addr:<44}  {info['trades']:>7}  ${info['pnl']:>10,.0f}  {cats}")
    w()

# Per-sport top 10
for sport in SPORTS:
    f = COWORK / f"{sport}_recon" / "losing_wallets.parquet"
    if not f.exists(): continue
    df = pd.read_parquet(f)
    df_top = df.head(10)
    w("=" * 78)
    w(f" TOP 10 LOSERS — {sport.upper()} (trailing 14 days)")
    w("=" * 78)
    w()
    w(f"{'#':>3}  {'wallet':<44}  {'trades':>7}  {'wr%':>5}  {'pnl_usd':>12}  {'roi%':>7}")
    w("-" * 100)
    for i, (w_addr, row) in enumerate(df_top.iterrows(), 1):
        w(f"{i:>3}  {w_addr:<44}  {int(row['trades']):>7}  {row['wr']:>5.0f}  "
          f"${row['pnl']:>10,.0f}  {row['roi']:>6.0f}")
    w()

w()
w("=" * 78)
w(" HOW TO LOOK UP A WALLET")
w("=" * 78)
w()
w(" Block explorer (all trades):")
w("   https://polygonscan.com/address/<WALLET>")
w()
w(" Polymarket profile:")
w("   https://polymarket.com/profile/<WALLET>")
w()
w(" Recent trades via Polymarket data-api:")
w("   https://data-api.polymarket.com/trades?user=<WALLET>&limit=50")
w()

# Write file
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {len(lines)} lines to {OUT}")
print(f"File size: {OUT.stat().st_size:,} bytes")
