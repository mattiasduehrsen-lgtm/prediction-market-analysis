"""Apply realistic execution friction to the OOS backtest.

Friction layers:
  1. Cancel rate: fraction of orders that never fill (no PnL).
     Esports LIVE data shows 40-45% cancel rate; sports likely similar
     given Polymarket indexer lag is the dominant factor.
  2. Extra slippage: actual fill price > quoted. Adds to cost / reduces shares.
     Sports markets are DEEPER than esports so slippage less severe.
  3. Indexer lag: trades we'd act on are 1-5 min old, so price has often
     moved. Modeled implicitly via cancel rate (orders that don't fill
     because price moved past us).

Runs the per-sport OPTIMAL parameter config and applies friction.
Reports: nominal OOS vs friction-adjusted, per-sport and combined.
"""
from __future__ import annotations
import json
import random
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
BET_USD = 5.0
SLIPPAGE_BASE = 0.01

# Per-sport optimal config from sports_backtest_sweep.py
OPTIMAL = {
    "nhl":    {"min_trades": 30, "min_roi": -15.0, "min_entry": 0.70},
    "nba":    {"min_trades": 30, "min_roi": -30.0, "min_entry": 0.40},
    "mlb":    {"min_trades": 50, "min_roi": -30.0, "min_entry": 0.40},
    "tennis": {"min_trades": 50, "min_roi": -15.0, "min_entry": 0.50},
    # Soccer: don't trade per sweep results.
}

# Friction scenarios to test
SCENARIOS = [
    ("perfect",        {"cancel_rate": 0.00, "extra_slip": 0.00}),
    ("optimistic",     {"cancel_rate": 0.20, "extra_slip": 0.01}),
    ("realistic",      {"cancel_rate": 0.40, "extra_slip": 0.02}),
    ("pessimistic",    {"cancel_rate": 0.55, "extra_slip": 0.04}),
]


def build_winner_map(clob_df, cids):
    sub = clob_df[clob_df["condition_id"].isin(cids)]
    winners = {}
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try: tl = list(tokens)
        except Exception: continue
        ws = [t for t in tl if isinstance(t, dict) and t.get("winner")]
        if len(ws) == 1: winners[row["condition_id"]] = ws[0].get("outcome", "")
    return winners


def get_targets_and_test(sport, clob_df, cfg):
    recon = COWORK / f"{sport}_recon"
    tf = recon / "trades.parquet"
    if not tf.exists(): return None
    trades = pd.read_parquet(tf)
    trades["proxyWallet"] = trades["proxyWallet"].astype(str).str.lower()
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["size"] = pd.to_numeric(trades["size"], errors="coerce")
    trades["timestamp"] = pd.to_numeric(trades["timestamp"], errors="coerce")
    trades = trades.dropna(subset=["price","size","timestamp","outcome","conditionId"])
    trades = trades[(trades["price"]>=0.05)&(trades["price"]<=0.95)&(trades["size"]>=1)]

    t_max = trades["timestamp"].max()
    train_end = t_max - 7 * 86400
    train = trades[trades["timestamp"] < train_end]
    test = trades[trades["timestamp"] >= train_end]

    all_cids = list(set(train["conditionId"]).union(set(test["conditionId"])))
    winners = build_winner_map(clob_df, all_cids)

    # Identify training-window targets
    tb = train[train["side"].str.upper()=="BUY"].copy()
    tb["winner"] = tb["conditionId"].map(winners)
    res = tb.dropna(subset=["winner"]).copy()
    res["won"] = res["outcome"] == res["winner"]
    res["cost"] = res["price"]*res["size"]
    res["pnl"] = res.apply(lambda r: r["size"]-r["cost"] if r["won"] else -r["cost"], axis=1)
    ts = res.groupby("proxyWallet").agg(
        trades=("pnl","size"), pnl=("pnl","sum"), cost=("cost","sum"))
    ts["roi"] = ts["pnl"]/ts["cost"].clip(lower=0.01)*100
    target_wallets = set(ts[(ts["trades"]>=cfg["min_trades"])
                            & (ts["roi"]<=cfg["min_roi"])].index)

    # Build cid_outs
    cid_outs = {}
    sub = clob_df[clob_df["condition_id"].isin(all_cids)]
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try:
            tl = list(tokens)
            outs = [t.get("outcome") for t in tl if isinstance(t, dict)]
            if len(outs)==2 and all(outs):
                cid_outs[row["condition_id"]] = outs
        except Exception: pass

    test_buys = test[(test["side"].str.upper()=="BUY")
                     & (test["proxyWallet"].isin(target_wallets))]
    return target_wallets, test_buys, winners, cid_outs


def simulate_with_friction(test_buys, winners, cid_outs, min_entry,
                            cancel_rate, extra_slip, seed=42):
    """Return per-trade list with friction applied."""
    rng = random.Random(seed)
    n_signals = n_cancelled = n_resolved = n_wins = n_losses = 0
    pnl_sum = cost_sum = 0.0
    for r in test_buys.itertuples(index=False):
        n_signals += 1
        cid = r.conditionId
        outs = cid_outs.get(cid)
        if not outs or r.outcome not in outs: continue
        our_out = [o for o in outs if o != r.outcome][0]
        our_entry = round(1 - float(r.price) + SLIPPAGE_BASE + extra_slip, 4)
        if our_entry < min_entry: continue

        # Cancel rate roll
        if rng.random() < cancel_rate:
            n_cancelled += 1
            continue

        win = winners.get(cid)
        if win is None: continue
        won = (our_out == win)
        cost = BET_USD
        pnl = (BET_USD / our_entry) - cost if won else -cost
        pnl_sum += pnl
        cost_sum += cost
        if won: n_wins += 1
        else: n_losses += 1
        n_resolved += 1

    return {
        "signals":     n_signals,
        "cancelled":   n_cancelled,
        "resolved":    n_resolved,
        "wins":        n_wins,
        "losses":      n_losses,
        "wr":          (n_wins/n_resolved*100) if n_resolved else 0,
        "pnl":         round(pnl_sum, 2),
        "cost":        round(cost_sum, 2),
        "roi":         (pnl_sum/cost_sum*100) if cost_sum else 0,
    }


def main():
    print("=" * 90)
    print(" FRICTION-ADJUSTED OOS BACKTEST")
    print("   Per-sport optimal config + 4 friction scenarios")
    print("=" * 90)
    print()

    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")
    print(f"Loaded {len(clob):,} clob markets\n")

    # Prep each sport
    sport_data = {}
    for sport, cfg in OPTIMAL.items():
        print(f"Prepping {sport} (cfg={cfg})...", flush=True)
        d = get_targets_and_test(sport, clob, cfg)
        if d is None: continue
        targets, test_buys, winners, cid_outs = d
        print(f"  {len(targets):,} targets, {len(test_buys):,} test buys")
        sport_data[sport] = (test_buys, winners, cid_outs, cfg, len(targets))

    # Sweep scenarios
    print()
    all_rows = []
    for scen_name, scen in SCENARIOS:
        print(f"--- Scenario: {scen_name}  (cancel={scen['cancel_rate']*100:.0f}%, "
              f"extra_slip={scen['extra_slip']*100:.0f}c) ---")
        scen_total_pnl = scen_total_cost = 0
        for sport, (tb, w, co, cfg, n_targets) in sport_data.items():
            r = simulate_with_friction(tb, w, co, cfg["min_entry"],
                                        scen["cancel_rate"], scen["extra_slip"])
            r.update({"sport": sport, "scenario": scen_name, **cfg, "n_targets": n_targets})
            r.update({"cancel_rate": scen["cancel_rate"],
                      "extra_slip":  scen["extra_slip"]})
            all_rows.append(r)
            scen_total_pnl += r["pnl"]
            scen_total_cost += r["cost"]
            sign = "+" if r["pnl"] >= 0 else "-"
            print(f"  {sport:<7} resolved={r['resolved']:>5,} WR={r['wr']:>4.1f}% "
                  f"PnL={sign}${abs(r['pnl']):>7,.0f}  ROI={r['roi']:>+6.2f}%")
        roi = scen_total_pnl / max(scen_total_cost,1) * 100
        sign = "+" if scen_total_pnl >= 0 else "-"
        print(f"  {'COMBINED':<7} {' ' * 25} {sign}${abs(scen_total_pnl):>7,.0f}  "
              f"ROI={roi:>+6.2f}%")
        print()

    # Save
    out = COWORK / "sports_backtest_friction.json"
    out.write_text(json.dumps({"rows": all_rows}, indent=2, default=str), encoding="utf-8")
    print(f"Saved to {out}")

    # Summary table
    print("=" * 90)
    print(" SUMMARY: COMBINED ROI ACROSS FRICTION SCENARIOS")
    print("=" * 90)
    print(f"{'Scenario':<14} {'cancel':>7} {'slip':>5} {'resolved':>9} {'PnL':>10} {'cost':>11} {'ROI':>8}")
    print("-" * 90)
    by_scen = defaultdict(lambda: {"resolved":0, "pnl":0.0, "cost":0.0})
    for r in all_rows:
        s = r["scenario"]
        by_scen[s]["resolved"] += r["resolved"]
        by_scen[s]["pnl"] += r["pnl"]
        by_scen[s]["cost"] += r["cost"]
    for scen_name, _ in SCENARIOS:
        v = by_scen[scen_name]
        roi = v["pnl"]/max(v["cost"],1)*100
        sign = "+" if v["pnl"]>=0 else "-"
        sc = next(s for n,s in SCENARIOS if n==scen_name)
        print(f"{scen_name:<14} {sc['cancel_rate']*100:>6.0f}% "
              f"{sc['extra_slip']*100:>4.0f}c {v['resolved']:>9,} "
              f"{sign}${abs(v['pnl']):>7,.0f}  ${v['cost']:>9,.0f}  {roi:>+6.2f}%")

    print()
    print("PRACTICAL TAKEAWAY:")
    print("  Use the 'realistic' scenario (40% cancel + 2c extra slip) as the")
    print("  expected LIVE performance baseline.  At that level, NBA and Tennis")
    print("  should remain profitable; NHL is too thin to be confident; MLB depends.")


if __name__ == "__main__":
    main()
