"""Parameter sweep: find OOS-optimal wallet selection criteria.

Hypothesis: deeper losers (more trades, more negative ROI in train window)
are more persistent than mild ones. Test multiple thresholds on the OOS
test period and report which combo has positive OOS ROI.

Also test entry-price floor variants since the OOS best bucket was $0.70-0.80,
not the in-sample's $0.50-0.60.
"""
from __future__ import annotations
import datetime as dt
import json
import time
from collections import defaultdict
from pathlib import Path
from itertools import product

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
SPORTS = ["nhl", "nba", "mlb", "tennis", "soccer"]
BET_USD = 5.0
SLIPPAGE = 0.01

# Sweep grid
MIN_TRADES_OPTS = [15, 30, 50]
MIN_ROI_OPTS    = [-5.0, -15.0, -30.0]
MIN_ENTRY_OPTS  = [0.40, 0.50, 0.60, 0.70]


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


def prep_sport(sport, clob_df):
    """Load trades + winners + cid_outs for a sport. Returns dict or None."""
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

    t_max = trades["timestamp"].max()
    train_end = t_max - 7 * 86400
    train = trades[trades["timestamp"] < train_end].copy()
    test = trades[trades["timestamp"] >= train_end].copy()

    all_cids = list(set(train["conditionId"].tolist() + test["conditionId"].tolist()))
    winners = build_winner_map(clob_df, all_cids)

    # Build train wallet stats once (independent of train thresholds)
    train_buys = train[train["side"].str.upper() == "BUY"].copy()
    train_buys["winner"] = train_buys["conditionId"].map(winners)
    resolved = train_buys.dropna(subset=["winner"]).copy()
    resolved["won"] = resolved["outcome"] == resolved["winner"]
    resolved["cost"] = resolved["price"] * resolved["size"]
    resolved["pnl"] = resolved.apply(
        lambda r: r["size"] - r["cost"] if r["won"] else -r["cost"], axis=1
    )
    train_stats = resolved.groupby("proxyWallet").agg(
        trades=("pnl","size"), pnl=("pnl","sum"), cost=("cost","sum"))
    train_stats["roi"] = train_stats["pnl"] / train_stats["cost"].clip(lower=0.01) * 100

    # Build cid_outs map
    cid_outs = {}
    sub = clob_df[clob_df["condition_id"].isin(all_cids)]
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try:
            tl = list(tokens)
            outs = [t.get("outcome") for t in tl if isinstance(t, dict)]
            if len(outs) == 2 and all(outs):
                cid_outs[row["condition_id"]] = outs
        except Exception: pass

    test_buys = test[test["side"].str.upper() == "BUY"].copy()
    return {"train_stats": train_stats, "test_buys": test_buys,
            "winners": winners, "cid_outs": cid_outs}


def simulate(sport_data, min_trades, min_roi, min_entry):
    """Run OOS simulation with given thresholds. Returns stats dict."""
    ts = sport_data["train_stats"]
    target_wallets = set(ts[(ts["trades"] >= min_trades) & (ts["roi"] <= min_roi)].index)

    test = sport_data["test_buys"]
    test = test[test["proxyWallet"].isin(target_wallets)]
    if len(test) == 0:
        return {"n_targets": len(target_wallets), "signals": 0, "resolved": 0,
                "wins": 0, "losses": 0, "pnl": 0.0, "cost": 0.0,
                "wr": 0, "roi": 0}

    winners = sport_data["winners"]
    cid_outs = sport_data["cid_outs"]

    n_sig = n_w = n_l = 0
    pnl_sum = cost_sum = 0.0
    for r in test.itertuples(index=False):
        n_sig += 1
        cid = r.conditionId
        outs = cid_outs.get(cid)
        if not outs or r.outcome not in outs: continue
        our_out = [o for o in outs if o != r.outcome][0]
        our_entry = round(1 - float(r.price) + SLIPPAGE, 4)
        if our_entry < min_entry: continue
        win = winners.get(cid)
        if win is None: continue
        won = (our_out == win)
        cost = BET_USD
        pnl = (BET_USD / our_entry) - cost if won else -cost
        pnl_sum += pnl
        cost_sum += cost
        if won: n_w += 1
        else: n_l += 1

    resolved = n_w + n_l
    return {
        "n_targets": len(target_wallets), "signals": n_sig, "resolved": resolved,
        "wins": n_w, "losses": n_l, "pnl": round(pnl_sum,2), "cost": round(cost_sum,2),
        "wr": (n_w/resolved*100) if resolved else 0,
        "roi": (pnl_sum/cost_sum*100) if cost_sum else 0,
    }


def main():
    print("=" * 88)
    print(" OOS PARAMETER SWEEP")
    print("   Goal: find selection criteria with positive OOS ROI per sport")
    print("=" * 88)

    print("\nLoading clob_markets.parquet...")
    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")
    print(f"  Loaded {len(clob):,}")

    # Preload each sport's data once
    print("\nPrepping each sport...")
    sport_data = {}
    for s in SPORTS:
        t0 = time.time()
        d = prep_sport(s, clob)
        if d is None:
            print(f"  {s}: skip"); continue
        sport_data[s] = d
        print(f"  {s}: {len(d['train_stats']):,} train wallets, "
              f"{len(d['test_buys']):,} test buys ({time.time()-t0:.1f}s)")

    # Sweep
    print("\nSweeping...")
    all_results = []
    for s, data in sport_data.items():
        for mt, mr, me in product(MIN_TRADES_OPTS, MIN_ROI_OPTS, MIN_ENTRY_OPTS):
            r = simulate(data, mt, mr, me)
            r["sport"] = s
            r["min_trades"] = mt
            r["min_roi"] = mr
            r["min_entry"] = me
            all_results.append(r)

    # Per-sport top combos
    for s in sport_data:
        print(f"\n=== {s.upper()} — top 8 OOS configurations ===")
        rs = [r for r in all_results if r["sport"] == s and r["resolved"] >= 30]
        rs.sort(key=lambda x: -x["roi"])
        print(f"{'trades':>6} {'roi':>5} {'entry':>5} {'targets':>7} {'resolved':>9} "
              f"{'WR':>5} {'PnL':>9} {'ROI':>8}")
        for r in rs[:8]:
            print(f"{r['min_trades']:>6} {r['min_roi']:>5} {r['min_entry']:>5} "
                  f"{r['n_targets']:>7,} {r['resolved']:>9,} {r['wr']:>4.1f}% "
                  f"${r['pnl']:>+7,.0f} {r['roi']:>+6.2f}%")

    # Find a single best COMBINED configuration (sums across sports)
    combos = defaultdict(lambda: {"n_resolved":0, "pnl":0.0, "cost":0.0, "sports":0})
    for r in all_results:
        if r["resolved"] < 30: continue  # too thin to count
        k = (r["min_trades"], r["min_roi"], r["min_entry"])
        combos[k]["n_resolved"] += r["resolved"]
        combos[k]["pnl"] += r["pnl"]
        combos[k]["cost"] += r["cost"]
        combos[k]["sports"] += 1

    print("\n" + "=" * 88)
    print(" BEST COMBINED CONFIGURATIONS (sum across all sports passing min volume)")
    print("=" * 88)
    print(f"{'trades':>6} {'roi':>5} {'entry':>5} {'#sports':>7} {'resolved':>9} {'PnL':>10} {'cost':>11} {'ROI':>8}")
    sorted_combos = sorted(combos.items(),
                            key=lambda kv: -(kv[1]["pnl"] / max(kv[1]["cost"], 1) * 100))
    for k, v in sorted_combos[:15]:
        mt, mr, me = k
        roi = v["pnl"] / max(v["cost"], 1) * 100
        print(f"{mt:>6} {mr:>5} {me:>5} {v['sports']:>7} {v['n_resolved']:>9,} "
              f"${v['pnl']:>+7,.0f}  ${v['cost']:>9,.0f}  {roi:>+6.2f}%")

    # Save
    out = COWORK / "sports_backtest_sweep.json"
    out.write_text(json.dumps({
        "results": all_results,
        "best_combined": [{"min_trades":k[0],"min_roi":k[1],"min_entry":k[2],
                           **v, "roi": v["pnl"]/max(v["cost"],1)*100}
                          for k,v in sorted_combos[:30]],
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved sweep to {out}")


if __name__ == "__main__":
    main()
