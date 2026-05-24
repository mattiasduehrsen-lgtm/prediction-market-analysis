"""How persistent is wallet-level losing behavior?

If "losing wallet in window 1" predicts "losing wallet in window 2", the
strategy is capturing real bad-bettor skill (lack thereof). If correlation
is zero, we're chasing noise and OOS performance comes from luck only.

Method: split each sport's 14d into 7d windows. For each wallet with
trades in BOTH windows, compute ROI in each. Plot scatter + correlation.
Also bucket by train ROI threshold and report: what % continue losing
(test ROI <= 0)?
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


def wallet_stats(buys_df, winners):
    buys_df = buys_df.copy()
    buys_df["winner"] = buys_df["conditionId"].map(winners)
    res = buys_df.dropna(subset=["winner"]).copy()
    res["won"] = res["outcome"] == res["winner"]
    res["cost"] = res["price"] * res["size"]
    res["pnl"] = res.apply(lambda r: r["size"]-r["cost"] if r["won"] else -r["cost"], axis=1)
    g = res.groupby("proxyWallet").agg(trades=("pnl","size"),
                                         pnl=("pnl","sum"), cost=("cost","sum"))
    g["roi"] = g["pnl"] / g["cost"].clip(lower=0.01) * 100
    return g


def analyze_sport(sport, clob_df):
    recon = COWORK / f"{sport}_recon"
    tf = recon / "trades.parquet"
    if not tf.exists(): return None
    trades = pd.read_parquet(tf)
    trades["proxyWallet"] = trades["proxyWallet"].astype(str).str.lower()
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["size"] = pd.to_numeric(trades["size"], errors="coerce")
    trades["timestamp"] = pd.to_numeric(trades["timestamp"], errors="coerce")
    trades = trades.dropna(subset=["price","size","timestamp","outcome","conditionId"])
    trades = trades[(trades["price"]>=0.05)&(trades["price"]<=0.95)&(trades["size"]>=1)
                     & (trades["side"].str.upper()=="BUY")]

    t_max = trades["timestamp"].max()
    train_end = t_max - 7 * 86400
    train_buys = trades[trades["timestamp"] < train_end]
    test_buys = trades[trades["timestamp"] >= train_end]

    cids = list(set(train_buys["conditionId"]).union(set(test_buys["conditionId"])))
    winners = build_winner_map(clob_df, cids)

    train_stats = wallet_stats(train_buys, winners)
    test_stats = wallet_stats(test_buys, winners)

    # Inner join — wallets with activity in BOTH windows
    combined = train_stats.join(test_stats, lsuffix="_train", rsuffix="_test", how="inner")
    if combined.empty:
        return None

    # Filter to wallets with meaningful train activity
    combined = combined[combined["trades_train"] >= 10]

    # Compute correlation between train ROI and test ROI
    if len(combined) >= 30:
        corr = combined["roi_train"].corr(combined["roi_test"])
    else:
        corr = float("nan")

    # By train-ROI threshold, what % continue losing in test?
    thresholds = [-5, -15, -30, -50]
    buckets = {}
    for thr in thresholds:
        sub = combined[combined["roi_train"] <= thr]
        if len(sub) == 0:
            buckets[thr] = None
            continue
        still_losing = sub[sub["roi_test"] <= 0]
        mean_roi_test = sub["roi_test"].mean()
        median_roi_test = sub["roi_test"].median()
        buckets[thr] = {
            "n":               len(sub),
            "pct_still_losing": len(still_losing)/len(sub)*100,
            "mean_test_roi":   round(mean_roi_test, 2),
            "median_test_roi": round(median_roi_test, 2),
        }

    return {
        "sport": sport,
        "n_wallets_overlap": len(combined),
        "correlation_train_test": round(corr, 3) if corr==corr else None,
        "buckets": buckets,
    }


def main():
    print("=" * 80)
    print(" WALLET PERSISTENCE ANALYSIS")
    print("   Question: do losing wallets in window 1 stay losing in window 2?")
    print("=" * 80)
    print()

    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")

    results = []
    for sport in SPORTS:
        print(f"=== {sport.upper()} ===")
        t0 = time.time()
        r = analyze_sport(sport, clob)
        if r is None: print("  skip"); continue
        results.append(r)
        print(f"  Wallets active in both windows: {r['n_wallets_overlap']:,}")
        print(f"  Train-ROI ~ Test-ROI correlation: {r['correlation_train_test']}")
        print(f"  Persistence by train threshold:")
        print(f"    {'thr':>5}  {'n':>5}  {'% still losing':>16}  {'mean test ROI':>15}  {'median':>10}")
        for thr in (-5, -15, -30, -50):
            v = r["buckets"].get(thr)
            if v is None: continue
            print(f"    <={thr:>4}%  {v['n']:>5,}  {v['pct_still_losing']:>15.1f}%  "
                  f"{v['mean_test_roi']:>14}%  {v['median_test_roi']:>9}%")
        print(f"  Elapsed: {time.time()-t0:.1f}s\n")

    # Save
    out = COWORK / "sports_wallet_persistence.json"
    out.write_text(json.dumps({"sports": results}, indent=2, default=str), encoding="utf-8")

    # Combined summary
    print("=" * 80)
    print(" COMBINED VIEW: pct of losers staying losers, by threshold")
    print("=" * 80)
    print(f"  {'sport':<8} {'corr':>7} {'thr=-5':>10} {'thr=-15':>10} {'thr=-30':>10} {'thr=-50':>10}")
    for r in results:
        line = f"  {r['sport']:<8} {str(r['correlation_train_test']):>7}"
        for thr in (-5, -15, -30, -50):
            v = r["buckets"].get(thr)
            if v: line += f" {v['pct_still_losing']:>9.1f}%"
            else: line += f" {'-':>10}"
        print(line)

    print()
    print("PRACTICAL TAKEAWAY:")
    print("  - Higher train-loss threshold (-30%, -50%) -> higher % continue losing")
    print("    if there's any real edge.  If pct stays ~50% across all thresholds,")
    print("    losing was just luck and OOS edge doesn't exist.")


if __name__ == "__main__":
    main()
