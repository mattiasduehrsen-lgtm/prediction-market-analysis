"""Out-of-sample backtest: identify losers on days 1-7, test on days 8-14.

The biggest risk in the in-sample backtest was using the same data to BOTH
identify targets AND simulate trading. This script splits the 14d window so
the test period is truly unseen when wallet selection happens.

Pipeline:
  TRAIN period: days 1-7. For each wallet, compute their PnL/ROI/trade count
    in this window. Keep wallets with n>=15 (relaxed from 30 since half window),
    ROI<=-5%.
  TEST period: days 8-14. Simulate fade strategy on signals from selected
    wallets only. Compute realized PnL.

OOS performance is the honest predictor of LIVE performance (modulo friction).
"""
from __future__ import annotations
import datetime as dt
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
SLIPPAGE = 0.01
TRAIN_DAYS = 7  # first half of 14d
MIN_TRADES_TRAIN = 15
MIN_ROI_TRAIN = -5.0  # ROI <= -5% to qualify as losing


def build_winner_map(clob_df, condition_ids):
    sub = clob_df[clob_df["condition_id"].isin(condition_ids)]
    winners = {}
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try: token_list = list(tokens)
        except Exception: continue
        ws = [t for t in token_list if isinstance(t, dict) and t.get("winner")]
        if len(ws) == 1:
            winners[row["condition_id"]] = ws[0].get("outcome", "")
    return winners


def compute_pnl_per_trade(row, winner_map):
    """Compute the buyer's PnL on a single BUY trade.
    win = size - cost (payout $1 per share)
    loss = -cost
    Returns (pnl, cost, won) or (None, None, None) if unresolved."""
    cid = row["conditionId"]
    out = row["outcome"]
    p = row["price"]; s = row["size"]
    cost = p * s
    w = winner_map.get(cid)
    if w is None: return None, None, None
    won = (out == w)
    return (s - cost if won else -cost), cost, won


def simulate_sport_oos(sport, clob_df):
    recon = COWORK / f"{sport}_recon"
    tf = recon / "trades.parquet"
    if not tf.exists(): return None
    trades = pd.read_parquet(tf)
    trades["proxyWallet"] = trades["proxyWallet"].astype(str).str.lower()
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["size"] = pd.to_numeric(trades["size"], errors="coerce")
    trades["timestamp"] = pd.to_numeric(trades["timestamp"], errors="coerce")
    trades = trades.dropna(subset=["price","size","timestamp","outcome","conditionId"])
    trades = trades[(trades["price"] >= 0.05) & (trades["price"] <= 0.95) & (trades["size"] >= 1)]

    # Time window
    t_max = trades["timestamp"].max()
    train_end = t_max - 7 * 86400  # last 7d = test, first 7d = train
    train = trades[trades["timestamp"] < train_end].copy()
    test = trades[trades["timestamp"] >= train_end].copy()

    # Build winner maps separately for each (mostly overlap, but be safe)
    all_cids = trades["conditionId"].unique().tolist()
    winners = build_winner_map(clob_df, all_cids)

    # ── TRAIN: identify losing wallets from days 1-7 ────────────────────────
    train_buys = train[train["side"].str.upper() == "BUY"].copy()
    pnls = []
    for r in train_buys.itertuples(index=False):
        pnl, cost, _ = compute_pnl_per_trade(r._asdict(), winners)
        pnls.append((pnl, cost))
    train_buys["pnl"] = [p[0] for p in pnls]
    train_buys["cost"] = [p[1] for p in pnls]
    train_buys = train_buys.dropna(subset=["pnl"])
    grp = train_buys.groupby("proxyWallet").agg(
        trades=("pnl","size"), pnl=("pnl","sum"), cost=("cost","sum"))
    grp["roi"] = grp["pnl"] / grp["cost"].clip(lower=0.01) * 100
    target_wallets = set(grp[(grp["trades"] >= MIN_TRADES_TRAIN)
                             & (grp["roi"] <= MIN_ROI_TRAIN)].index)

    # ── TEST: simulate fade on TARGET-WALLET BUYs in days 8-14 ──────────────
    test_buys = test[(test["side"].str.upper() == "BUY")
                     & (test["proxyWallet"].isin(target_wallets))].copy()

    # Build cid -> outcomes map for opposite lookups
    cid_outs = {}
    sub = clob_df[clob_df["condition_id"].isin(test_buys["conditionId"].unique())]
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try:
            tl = list(tokens)
            outs = [t.get("outcome") for t in tl if isinstance(t, dict)]
            if len(outs) == 2 and all(outs):
                cid_outs[row["condition_id"]] = outs
        except Exception: pass

    n_sig = n_floor = n_unres = n_wins = n_losses = 0
    total_pnl = total_cost = 0.0
    bucket = defaultdict(lambda: {"n":0,"w":0,"l":0,"pnl":0.0,"cost":0.0})
    for r in test_buys.itertuples(index=False):
        n_sig += 1
        cid = r.conditionId
        their_out = r.outcome
        their_p = float(r.price)
        outs = cid_outs.get(cid)
        if not outs or their_out not in outs: continue
        our_out = [o for o in outs if o != their_out][0]
        our_entry = round(1 - their_p + SLIPPAGE, 4)
        if our_entry < MIN_ENTRY:
            n_floor += 1
            continue
        win = winners.get(cid)
        if win is None:
            n_unres += 1
            continue
        won = (our_out == win)
        cost = BET_USD
        shares = BET_USD / our_entry
        pnl = shares - cost if won else -cost
        total_pnl += pnl
        total_cost += cost
        if won: n_wins += 1
        else: n_losses += 1
        if our_entry < 0.50: b = "$0.40-0.50"
        elif our_entry < 0.60: b = "$0.50-0.60"
        elif our_entry < 0.70: b = "$0.60-0.70"
        elif our_entry < 0.80: b = "$0.70-0.80"
        elif our_entry < 0.90: b = "$0.80-0.90"
        else: b = "$0.90+"
        bucket[b]["n"] += 1
        bucket[b]["pnl"] += pnl
        bucket[b]["cost"] += cost
        if won: bucket[b]["w"] += 1
        else: bucket[b]["l"] += 1

    resolved = n_wins + n_losses
    return {
        "sport": sport,
        "train_window_days": TRAIN_DAYS,
        "train_target_wallets": len(target_wallets),
        "test_signals":         n_sig,
        "test_filtered_floor":  n_floor,
        "test_resolved":        resolved,
        "test_unresolved":      n_unres,
        "wins": n_wins, "losses": n_losses,
        "wr_pct": (n_wins/resolved*100) if resolved else 0,
        "total_pnl": round(total_pnl, 2),
        "total_cost": round(total_cost, 2),
        "roi_pct": (total_pnl/total_cost*100) if total_cost else 0,
        "by_bucket": dict(bucket),
    }


def main():
    print("=" * 78)
    print(" SPORTS OUT-OF-SAMPLE BACKTEST")
    print(f"   Train: first {TRAIN_DAYS}d -> identify losing wallets")
    print(f"   Test:  last {TRAIN_DAYS}d -> fade them, compute realized PnL")
    print("=" * 78)
    print()

    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")
    print(f"  Loaded {len(clob):,} clob markets\n")

    results = []
    for sport in SPORTS:
        t0 = time.time()
        print(f"=== {sport.upper()} ===")
        r = simulate_sport_oos(sport, clob)
        if r is None:
            print("  skip — no data"); continue
        results.append(r)
        sign = "+" if r["total_pnl"] >= 0 else "-"
        print(f"  Train wallets identified: {r['train_target_wallets']:,}")
        print(f"  Test signals: {r['test_signals']:,} "
              f"(filtered: {r['test_filtered_floor']:,}, unres: {r['test_unresolved']:,})")
        print(f"  Resolved:     {r['test_resolved']:,}  "
              f"({r['wins']} W / {r['losses']} L, {r['wr_pct']:.1f}% WR)")
        print(f"  PnL:          {sign}${abs(r['total_pnl']):,.2f}  on ${r['total_cost']:,.2f}")
        print(f"  ROI:          {r['roi_pct']:+.2f}%")
        print(f"  Elapsed:      {time.time()-t0:.1f}s")
        print()

    # Combined
    print("=" * 78)
    print(" COMBINED OOS — all sports")
    print("=" * 78)
    print(f"{'Sport':<10} {'wallets':>8} {'signals':>8} {'resolved':>9} {'WR':>6} {'PnL':>10} {'cost':>11} {'ROI':>8}")
    print("-" * 78)
    tot_pnl = tot_cost = 0; tot_w = tot_l = tot_resolved = 0
    for r in sorted(results, key=lambda x: -x["roi_pct"]):
        sign = "+" if r["total_pnl"] >= 0 else "-"
        print(f"{r['sport']:<10} {r['train_target_wallets']:>8,} {r['test_signals']:>8,} "
              f"{r['test_resolved']:>9,} {r['wr_pct']:>5.1f}% {sign}${abs(r['total_pnl']):>7,.2f} "
              f"${r['total_cost']:>9,.2f} {r['roi_pct']:>+6.2f}%")
        tot_pnl += r["total_pnl"]; tot_cost += r["total_cost"]
        tot_w += r["wins"]; tot_l += r["losses"]; tot_resolved += r["test_resolved"]
    print("-" * 78)
    wr = tot_w / max(tot_resolved, 1) * 100
    roi = tot_pnl / max(tot_cost, 1) * 100
    sign = "+" if tot_pnl >= 0 else "-"
    print(f"{'TOTAL':<10} {'':>8} {'':>8} {tot_resolved:>9,} {wr:>5.1f}% "
          f"{sign}${abs(tot_pnl):>7,.2f} ${tot_cost:>9,.2f} {roi:>+6.2f}%")
    print()

    # Bucket
    bt = defaultdict(lambda: {"n":0,"w":0,"l":0,"pnl":0.0,"cost":0.0})
    for r in results:
        for b, v in r["by_bucket"].items():
            for k in ("n","w","l","pnl","cost"): bt[b][k] += v[k]
    print("Entry-price buckets:")
    print(f"{'bucket':<14} {'n':>6} {'W/L':>10} {'WR':>6} {'PnL':>10} {'ROI':>8}")
    order = ["$0.40-0.50","$0.50-0.60","$0.60-0.70","$0.70-0.80","$0.80-0.90","$0.90+"]
    for b in order:
        if b not in bt: continue
        v = bt[b]
        wr = v["w"] / max(v["n"], 1) * 100
        roi = v["pnl"] / max(v["cost"], 1) * 100
        sign = "+" if v["pnl"] >= 0 else "-"
        print(f"{b:<14} {v['n']:>6} {v['w']:>4}/{v['l']:<4} {wr:>5.1f}% "
              f"{sign}${abs(v['pnl']):>7,.2f} {roi:>+6.2f}%")

    # Save
    out_path = COWORK / "sports_backtest_oos_results.json"
    out_path.write_text(json.dumps({
        "results": [{k:v for k,v in r.items() if k != "by_bucket"} for r in results],
        "totals": {"resolved": tot_resolved, "wr": round(wr,2),
                   "pnl": round(tot_pnl,2), "cost": round(tot_cost,2), "roi": round(roi,2)},
        "buckets": {b: dict(v) for b,v in bt.items()},
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
