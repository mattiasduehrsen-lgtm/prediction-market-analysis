"""
Cross-check bulk_blockchain_trades_part{N}.zip filtered esports trades against
our data-api scrape and current fade/follow targets.

Answers:
  1. Date range + volume of esports trades in bulk parts
  2. Does the bulk data contain trades not in our data-api scrape?
     (i.e., is our scrape complete for the bulk's date range?)
  3. Any wallets in the bulk with significant losses that AREN'T in
     fade_targets.json? They might be persistent losers we missed
     because they went quiet in the last 14 days.

Inputs:
  cowork_snapshot/esports/esports_trades_part2.parquet  (from filter)
  cowork_snapshot/esports/esports_trades_part3.parquet  (from filter)
  cowork_snapshot/esports/scrape/shards/*.parquet       (data-api scrape)
  cowork_snapshot/esports/resolutions.parquet
  cowork_snapshot/esports/fade_targets.json

Usage:
  .venv\\Scripts\\python.exe analysis\\analyze_bulk_findings.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
BET = 5.0


def determine_won_bulk(df):
    """Bulk schema: token_id + side (BUY/SELL).

    We don't have outcome per token from the bulk row, so we look up
    winning_token from resolutions and compare.
    """
    # df['token_id'] vs df['winning_token']
    # If side=BUY and token == winning_token: won
    # If side=SELL and token != winning_token: won
    sell = df["side"].astype(str).str.upper() == "SELL"
    matches_winner = df["token_id"].astype(str) == df["winning_token"].astype(str)
    return np.where(sell, ~matches_winner, matches_winner)


def pnl_from_price(price, won, bet=BET):
    p = np.clip(price.astype(float), 0.05, 0.95)
    shares = bet / p
    return np.where(won, shares - bet, -bet)


def main():
    # 1) Load all bulk parts
    bulk_parts = sorted(ES.glob("esports_trades_part*.parquet"))
    if not bulk_parts:
        print("No bulk esports parquets found. Run filter_trades_to_esports.py first.")
        return
    print(f"Found {len(bulk_parts)} bulk part(s): {[p.name for p in bulk_parts]}")
    bulk = pd.concat([pd.read_parquet(p) for p in bulk_parts], ignore_index=True)
    print(f"  total bulk esports trades: {len(bulk):,}")
    print(f"  date range: {bulk['datetime_utc'].min()} → {bulk['datetime_utc'].max()}")
    print(f"  unique markets: {bulk['condition_id'].nunique():,}")
    print(f"  unique participants (maker+taker): "
          f"{len(set(bulk['maker']).union(set(bulk['taker']))):,}")
    print()

    # 2) Coverage check vs our data-api scrape
    print("=" * 60)
    print("COVERAGE: bulk vs data-api scrape")
    print("=" * 60)
    shards = sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet")))
    scrape = pd.concat([pd.read_parquet(s, columns=["conditionId","timestamp","proxyWallet","price","size"]) for s in shards], ignore_index=True)
    scrape["timestamp"] = pd.to_numeric(scrape["timestamp"], errors="coerce")
    print(f"  data-api scrape rows: {len(scrape):,}")

    bulk["timestamp_int"] = pd.to_numeric(bulk["timestamp"], errors="coerce").astype("Int64")
    bulk_range_lo = int(bulk["timestamp_int"].min() or 0)
    bulk_range_hi = int(bulk["timestamp_int"].max() or 0)
    scrape_in_window = scrape[(scrape["timestamp"] >= bulk_range_lo) & (scrape["timestamp"] <= bulk_range_hi)]
    print(f"  data-api rows in bulk's date window: {len(scrape_in_window):,}")
    print(f"  bulk rows                          : {len(bulk):,}")
    delta = len(scrape_in_window) - len(bulk)
    if abs(delta) / max(len(bulk), 1) < 0.10:
        print(f"  -> within 10% — coverage looks consistent")
    elif delta > 0:
        print(f"  -> data-api has {delta:+,} more rows than bulk for this window")
    else:
        print(f"  -> bulk has {-delta:+,} more rows than data-api — potential gap")

    # 3) New wallets analysis: who's losing big in bulk but not in our current targets?
    print()
    print("=" * 60)
    print("UNTRACKED LOSERS: in bulk but not in fade_targets.json")
    print("=" * 60)

    # Load resolutions
    res = pd.read_parquet(ES / "resolutions.parquet")[
        ["condition_id","winning_outcome","winning_token","resolved"]
    ]
    bulk_m = bulk.merge(res, on="condition_id", how="left")
    bulk_m = bulk_m[bulk_m["resolved"] & bulk_m["winning_token"].notna()].copy()

    # determine win + PnL per row (proxy: each row = $5 bet, normalized)
    bulk_m["won"] = determine_won_bulk(bulk_m)
    bulk_m["pnl"] = pnl_from_price(bulk_m["price"], bulk_m["won"])

    # Per-wallet aggregation — bulk has maker AND taker per trade.
    # For each trade, BOTH parties trade; their PnL is opposite-signed but
    # not necessarily symmetric (depends on which side they took).
    # Simplification: attribute to TAKER (the active party) — matches
    # data-api semantics (proxyWallet = taker).
    bulk_m["wallet"] = bulk_m["taker"].astype(str).str.lower()

    g = bulk_m.groupby("wallet").agg(
        trades=("pnl", "size"),
        wins=("won", "sum"),
        pnl=("pnl", "sum"),
        last_ts=("timestamp_int", "max"),
    ).reset_index()
    g["wr"]  = (g["wins"] / g["trades"] * 100).round(2)
    g["roi"] = (g["pnl"] / (g["trades"] * BET) * 100).round(2)

    # Current fade targets
    try:
        ft = json.loads((ES / "fade_targets.json").read_text(encoding="utf-8"))
        current_targets = set(w.lower() for w in ft.get("target_wallets", []))
    except Exception:
        current_targets = set()
    print(f"  current fade targets: {len(current_targets)}")

    # Find untracked losers: n>=30 trades in bulk, pnl < -$200, NOT in targets
    candidates = g[
        (g["trades"] >= 30) &
        (g["pnl"] < -200) &
        (~g["wallet"].isin(current_targets))
    ].sort_values("pnl").head(25)

    if not len(candidates):
        print("  No new untracked losers found in bulk that aren't already in targets.")
    else:
        print(f"  {len(candidates)} untracked losers with n>=30 trades and bulk PnL<-$200:")
        print()
        print(candidates[["wallet","trades","wr","pnl","roi"]].to_string(index=False))
        print()
        print("  These wallets traded heavily and lost during the bulk's date window")
        print("  but aren't in our current fade list. Two reasons possible:")
        print("    (a) they stopped trading in the last 14d -> excluded by 'active' filter")
        print("    (b) bulk's PnL view differs from ours (proxy_wallet vs taker)")

    # 4) Check tracked targets — did any improve / stop losing in bulk?
    print()
    print("=" * 60)
    print("CURRENT TARGETS: any flips to winning in bulk window?")
    print("=" * 60)
    tracked = g[g["wallet"].isin(current_targets)].copy()
    if not len(tracked):
        print("  No overlap between bulk takers and current fade list.")
    else:
        print(f"  overlap: {len(tracked)} of {len(current_targets)} targets seen in bulk")
        # Were any actually profitable in this window?
        flippers = tracked[(tracked["trades"] >= 10) & (tracked["roi"] > 10)].sort_values("pnl", ascending=False).head(10)
        if len(flippers):
            print(f"\n  WARNING: {len(flippers)} 'losing' targets were actually PROFITABLE in bulk window:")
            print(flippers[["wallet","trades","wr","pnl","roi"]].to_string(index=False))
            print("  These may have become winners — consider dropping from fade list.")
        else:
            print("  No tracked targets flipped to profitable — current list looks stable.")


if __name__ == "__main__":
    main()
