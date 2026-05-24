"""Backtest the fade-the-losers strategy on historical sports trade data.

For each sport we already have:
  cowork_snapshot/{sport}_recon/trades.parquet           — all trades in 14d window
  cowork_snapshot/{sport}_recon/losing_wallets.parquet   — qualifying targets
  cowork_snapshot/esports/clob_markets.parquet           — winner per market

Simulates the live bot's behavior:
  - Only BUYs from qualifying losing wallets
  - $0.40 entry-price floor
  - $5 paper bet
  - Compute PnL using actual market resolution

Reports: per-sport signals, WR, PnL, ROI + overall aggregate + entry-price buckets.

This is an in-sample backtest — the "qualifying losing wallets" were identified
using the same 14d window we're now backtesting. Numbers will be optimistic vs
out-of-sample. But it's enough to validate whether the strategy mechanically
works on sports.
"""
from __future__ import annotations
import json
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
SPORTS = ["nhl", "nba", "mlb", "tennis", "soccer"]
BET_USD = 5.0
MIN_ENTRY = 0.40
SLIPPAGE = 0.01  # our_entry = (1 - their_price) + slippage


def build_winner_map(clob_df, condition_ids):
    """For a set of condition_ids, return {cid: winning_outcome_string}."""
    sub = clob_df[clob_df["condition_id"].isin(condition_ids)]
    winners = {}
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None:
            continue
        try:
            token_list = list(tokens)
        except Exception:
            continue
        ws = [t for t in token_list if isinstance(t, dict) and t.get("winner")]
        if len(ws) == 1:
            winners[row["condition_id"]] = ws[0].get("outcome", "")
    return winners


def simulate_sport(sport, clob_df):
    """Run the backtest for one sport. Returns a dict of stats."""
    recon = COWORK / f"{sport}_recon"
    tf = recon / "trades.parquet"
    wf = recon / "losing_wallets.parquet"
    if not tf.exists() or not wf.exists():
        return None

    trades = pd.read_parquet(tf)
    wallets_df = pd.read_parquet(wf)
    target_wallets = set(w.lower() for w in wallets_df.index)

    # Normalize fields
    trades["proxyWallet"] = trades["proxyWallet"].astype(str).str.lower()
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["size"] = pd.to_numeric(trades["size"], errors="coerce")
    trades["timestamp"] = pd.to_numeric(trades["timestamp"], errors="coerce")
    trades = trades.dropna(subset=["price", "size", "timestamp", "outcome", "conditionId"])

    # Only BUYs from target wallets, dust filter (size >= 1)
    target_trades = trades[
        (trades["proxyWallet"].isin(target_wallets))
        & (trades["side"].str.upper() == "BUY")
        & (trades["size"] >= 1)
        & (trades["price"] >= 0.05)
        & (trades["price"] <= 0.95)
    ].copy()

    cids = target_trades["conditionId"].unique().tolist()
    winners = build_winner_map(clob_df, cids)

    # Map markets to their two outcomes so we know what "opposite" is
    cid_outcomes = {}  # cid -> list of outcomes
    sub = clob_df[clob_df["condition_id"].isin(cids)]
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None:
            continue
        try:
            token_list = list(tokens)
            outs = [t.get("outcome") for t in token_list if isinstance(t, dict)]
            if len(outs) == 2 and all(outs):
                cid_outcomes[row["condition_id"]] = outs
        except Exception:
            pass

    # Simulate per signal
    n_signals = n_filtered_floor = n_resolved = n_unresolved = 0
    n_wins = n_losses = 0
    total_pnl = 0.0
    total_cost = 0.0
    by_bucket = defaultdict(lambda: {"n": 0, "w": 0, "l": 0, "pnl": 0.0, "cost": 0.0})
    by_wallet = defaultdict(lambda: {"n": 0, "w": 0, "l": 0, "pnl": 0.0})

    for _, t in target_trades.iterrows():
        n_signals += 1
        cid = t["conditionId"]
        their_outcome = t["outcome"]
        their_price = float(t["price"])

        outs = cid_outcomes.get(cid)
        if not outs or their_outcome not in outs:
            continue
        our_outcome = [o for o in outs if o != their_outcome][0]
        our_entry = round(1 - their_price + SLIPPAGE, 4)

        # Filter: $0.40 floor
        if our_entry < MIN_ENTRY:
            n_filtered_floor += 1
            continue

        # Look up resolution
        winner = winners.get(cid)
        if winner is None:
            n_unresolved += 1
            continue
        n_resolved += 1

        won = (our_outcome == winner)
        cost = BET_USD
        shares = BET_USD / our_entry
        if won:
            payout = shares  # × $1
            pnl = payout - cost
            n_wins += 1
        else:
            pnl = -cost
            n_losses += 1
        total_pnl += pnl
        total_cost += cost

        # Bucket
        if our_entry < 0.50: b = "$0.40-0.50"
        elif our_entry < 0.60: b = "$0.50-0.60"
        elif our_entry < 0.70: b = "$0.60-0.70"
        elif our_entry < 0.80: b = "$0.70-0.80"
        elif our_entry < 0.90: b = "$0.80-0.90"
        else: b = "$0.90+"
        by_bucket[b]["n"] += 1
        by_bucket[b]["pnl"] += pnl
        by_bucket[b]["cost"] += cost
        if won: by_bucket[b]["w"] += 1
        else:   by_bucket[b]["l"] += 1

        # Per wallet
        w = t["proxyWallet"]
        by_wallet[w]["n"] += 1
        by_wallet[w]["pnl"] += pnl
        if won: by_wallet[w]["w"] += 1
        else:   by_wallet[w]["l"] += 1

    return {
        "sport": sport,
        "raw_target_buys":  len(target_trades),
        "n_signals":        n_signals,
        "n_filtered_floor": n_filtered_floor,
        "n_resolved":       n_resolved,
        "n_unresolved":     n_unresolved,
        "wins":             n_wins,
        "losses":           n_losses,
        "wr_pct":           (n_wins / n_resolved * 100) if n_resolved else 0,
        "total_pnl":        round(total_pnl, 2),
        "total_cost":       round(total_cost, 2),
        "roi_pct":          (total_pnl / total_cost * 100) if total_cost else 0,
        "by_bucket":        dict(by_bucket),
        "top_wallets":      sorted(by_wallet.items(), key=lambda x: -x[1]["pnl"])[:5]
                            + sorted(by_wallet.items(), key=lambda x: x[1]["pnl"])[:5],
    }


def main():
    print("Loading clob_markets.parquet (winners lookup)...")
    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")
    print(f"  Loaded {len(clob):,} markets")
    print()

    results = []
    for sport in SPORTS:
        print(f"=== {sport.upper()} ===")
        t0 = time.time()
        r = simulate_sport(sport, clob)
        if r is None:
            print("  skip — missing files")
            continue
        results.append(r)
        sign = "+" if r["total_pnl"] >= 0 else "-"
        print(f"  Signals processed:    {r['n_signals']:,}")
        print(f"  Filtered out (<$0.40): {r['n_filtered_floor']:,}")
        print(f"  Resolved:             {r['n_resolved']:,}  ({r['n_unresolved']:,} unresolved)")
        print(f"  Wins/Losses:          {r['wins']:,} / {r['losses']:,}  "
              f"({r['wr_pct']:.1f}% WR)")
        print(f"  Total cost:           ${r['total_cost']:,.2f}")
        print(f"  Total PnL:            {sign}${abs(r['total_pnl']):,.2f}")
        print(f"  ROI:                  {r['roi_pct']:+.2f}%")
        print(f"  Elapsed:              {time.time()-t0:.1f}s")
        print()

    # Combined summary
    print("=" * 72)
    print(" COMBINED — all sports")
    print("=" * 72)
    print()
    print(f"{'Sport':<10} {'signals':>8} {'wins':>6} {'losses':>6} "
          f"{'WR':>6} {'PnL':>10} {'cost':>10} {'ROI':>8}")
    print("-" * 72)
    for r in sorted(results, key=lambda x: -x["total_pnl"]):
        sign = "+" if r["total_pnl"] >= 0 else "-"
        print(f"{r['sport']:<10} {r['n_resolved']:>8,} {r['wins']:>6,} {r['losses']:>6,} "
              f"{r['wr_pct']:>5.1f}%  {sign}${abs(r['total_pnl']):>7,.2f}  "
              f"${r['total_cost']:>8,.2f}  {r['roi_pct']:>+6.2f}%")
    print()
    tot_pnl = sum(r["total_pnl"] for r in results)
    tot_cost = sum(r["total_cost"] for r in results)
    tot_resolved = sum(r["n_resolved"] for r in results)
    tot_wins = sum(r["wins"] for r in results)
    tot_losses = sum(r["losses"] for r in results)
    wr = tot_wins / max(tot_resolved, 1) * 100
    roi = tot_pnl / max(tot_cost, 1) * 100
    sign = "+" if tot_pnl >= 0 else "-"
    print(f"{'TOTAL':<10} {tot_resolved:>8,} {tot_wins:>6,} {tot_losses:>6,} "
          f"{wr:>5.1f}%  {sign}${abs(tot_pnl):>7,.2f}  ${tot_cost:>8,.2f}  "
          f"{roi:>+6.2f}%")
    print()

    # Combined bucket analysis
    print("Entry-price bucket analysis (all sports combined):")
    print(f"{'bucket':<14} {'n':>5} {'W/L':>9} {'WR':>6} {'PnL':>10} {'cost':>10} {'ROI':>8}")
    bucket_totals = defaultdict(lambda: {"n":0,"w":0,"l":0,"pnl":0.0,"cost":0.0})
    for r in results:
        for b, v in r["by_bucket"].items():
            for k in ("n","w","l","pnl","cost"):
                bucket_totals[b][k] += v[k]
    order = ["$0.40-0.50","$0.50-0.60","$0.60-0.70","$0.70-0.80","$0.80-0.90","$0.90+"]
    for b in order:
        if b not in bucket_totals: continue
        v = bucket_totals[b]
        wr = v["w"] / max(v["n"], 1) * 100
        roi = v["pnl"] / max(v["cost"], 1) * 100
        sign = "+" if v["pnl"] >= 0 else "-"
        print(f"{b:<14} {v['n']:>5} {v['w']:>4}/{v['l']:<4} {wr:>5.1f}% "
              f"{sign}${abs(v['pnl']):>7,.2f} ${v['cost']:>8,.2f} {roi:>+6.2f}%")

    # Save full results
    out = COWORK / "sports_backtest_results.json"
    out.write_text(json.dumps({
        "results": [
            {k: v for k, v in r.items() if k not in ("by_bucket","top_wallets")}
            for r in results
        ],
        "totals": {
            "resolved": tot_resolved, "wins": tot_wins, "losses": tot_losses,
            "wr": round(wr, 2), "pnl": round(tot_pnl, 2), "cost": round(tot_cost, 2),
            "roi": round(roi, 2),
        },
        "buckets": {b: dict(v) for b, v in bucket_totals.items()},
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved full results to {out}")


if __name__ == "__main__":
    main()
