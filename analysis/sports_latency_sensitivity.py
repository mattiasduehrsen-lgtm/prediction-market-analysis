"""How sensitive is OOS ROI to acting-on-stale-data?

When the bot sees a target trade, it's already X seconds old (Polymarket
indexer lag + our poll interval). By the time we'd submit a fade, the price
may have moved. This script bins target trades by their age-at-detection
and computes fade outcomes per bin.

Hypothesis: target wallets that traded RECENTLY (low lag) should fade with
higher WR / ROI than ones we caught late. If true, latency improvements
matter directly. If WR is flat across lag bins, latency doesn't matter much.

For backtest, we don't have real signal_seen_at timestamps, so we proxy
'lag at trade time' by binning trades by their position within the test
window. As a fallback, we test: does ROI decay if we ONLY trade signals
where MULTIPLE wallets fired on the same market in a short window
(consensus signal, less time-sensitive)?
"""
from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
SPORTS = ["nba", "mlb", "tennis"]
BET_USD = 5.0
SLIPPAGE = 0.01

OPTIMAL = {
    "nhl":    {"min_trades": 30, "min_roi": -15.0, "min_entry": 0.70},
    "nba":    {"min_trades": 30, "min_roi": -30.0, "min_entry": 0.40},
    "mlb":    {"min_trades": 50, "min_roi": -30.0, "min_entry": 0.40},
    "tennis": {"min_trades": 50, "min_roi": -15.0, "min_entry": 0.50},
}


def build_winner_map(clob_df, cids):
    sub = clob_df[clob_df["condition_id"].isin(cids)]
    w = {}
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try: tl = list(tokens)
        except: continue
        ws = [t for t in tl if isinstance(t,dict) and t.get("winner")]
        if len(ws)==1: w[row["condition_id"]] = ws[0].get("outcome","")
    return w


def get_test_signals(sport, clob_df, cfg):
    """Return DataFrame of test-period signals (with PnL computed at our_entry)."""
    recon = COWORK / f"{sport}_recon"
    trades = pd.read_parquet(recon / "trades.parquet")
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
    res["won"] = res["outcome"]==res["winner"]
    res["cost"] = res["price"]*res["size"]
    res["pnl"] = res.apply(lambda r: r["size"]-r["cost"] if r["won"] else -r["cost"], axis=1)
    ts = res.groupby("proxyWallet").agg(
        trades=("pnl","size"), pnl=("pnl","sum"), cost=("cost","sum"))
    ts["roi"] = ts["pnl"]/ts["cost"].clip(lower=0.01)*100
    targets = set(ts[(ts["trades"]>=cfg["min_trades"])
                      & (ts["roi"]<=cfg["min_roi"])].index)

    # cid_outs
    cid_outs = {}
    sub = clob_df[clob_df["condition_id"].isin(all_cids)]
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try:
            tl = list(tokens)
            outs = [t.get("outcome") for t in tl if isinstance(t,dict)]
            if len(outs)==2 and all(outs):
                cid_outs[row["condition_id"]] = outs
        except: pass

    test_buys = test[(test["side"].str.upper()=="BUY")
                      & (test["proxyWallet"].isin(targets))].copy()

    # For each signal, compute pnl as if we'd faded with $5
    sigs = []
    for r in test_buys.itertuples(index=False):
        cid = r.conditionId
        outs = cid_outs.get(cid)
        if not outs or r.outcome not in outs: continue
        our_out = [o for o in outs if o!=r.outcome][0]
        our_entry = round(1 - float(r.price) + SLIPPAGE, 4)
        if our_entry < cfg["min_entry"]: continue
        win = winners.get(cid)
        if win is None: continue
        won = (our_out == win)
        pnl = (BET_USD/our_entry) - BET_USD if won else -BET_USD
        sigs.append({
            "ts": float(r.timestamp), "cid": cid,
            "wallet": r.proxyWallet, "our_entry": our_entry,
            "won": won, "pnl": pnl,
        })
    return pd.DataFrame(sigs)


def consensus_lag_test(sigs):
    """If multiple target wallets fire on the same market within X seconds,
    does the 2nd/3rd one have lower ROI than the 1st?"""
    if sigs.empty: return None
    sigs = sigs.sort_values(["cid","ts"]).copy()
    # Per market, rank in time order
    sigs["rank_in_market"] = sigs.groupby("cid").cumcount() + 1
    # Lag (s) from first signal in market
    sigs["lag_from_first"] = sigs.groupby("cid")["ts"].transform(lambda s: s - s.iloc[0])

    # Bucket by rank
    rank_stats = []
    for rnk in [1, 2, 3, 4]:
        sub = sigs[sigs["rank_in_market"] == rnk]
        if len(sub) < 30: continue
        wr = sub["won"].mean() * 100
        pnl = sub["pnl"].sum()
        cost = len(sub) * BET_USD
        roi = pnl / max(cost, 1) * 100
        rank_stats.append({"rank": rnk, "n": len(sub), "wr": wr,
                            "pnl": round(pnl, 2), "roi": roi})
    # 5+ bucketed together
    sub = sigs[sigs["rank_in_market"] >= 5]
    if len(sub) >= 30:
        wr = sub["won"].mean() * 100
        pnl = sub["pnl"].sum()
        cost = len(sub) * BET_USD
        roi = pnl / max(cost, 1) * 100
        rank_stats.append({"rank": "5+", "n": len(sub), "wr": wr,
                            "pnl": round(pnl, 2), "roi": roi})
    return rank_stats


def lag_test(sigs):
    """Bucket by lag-from-first-signal-in-market.
    If ROI drops as lag rises, latency matters."""
    if sigs.empty: return None
    sigs = sigs.sort_values(["cid","ts"]).copy()
    sigs["lag_from_first"] = sigs.groupby("cid")["ts"].transform(lambda s: s - s.iloc[0])
    lag_buckets = [(0, 0, "1st in market"),
                   (1, 60, "1-60s"),
                   (61, 300, "1-5min"),
                   (301, 1800, "5-30min"),
                   (1801, 3600, "30-60min"),
                   (3601, 86400, "1h+")]
    out = []
    for low, high, label in lag_buckets:
        if low == 0 and high == 0:
            sub = sigs[sigs["lag_from_first"] == 0]
        else:
            sub = sigs[(sigs["lag_from_first"] >= low)
                       & (sigs["lag_from_first"] <= high)]
        if len(sub) < 30: continue
        wr = sub["won"].mean() * 100
        pnl = sub["pnl"].sum()
        roi = pnl / (len(sub) * BET_USD) * 100
        out.append({"lag_bucket": label, "n": len(sub), "wr": wr,
                    "pnl": round(pnl,2), "roi": roi})
    return out


def main():
    print("=" * 80)
    print(" LATENCY SENSITIVITY")
    print("=" * 80)
    print()

    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")

    for sport in SPORTS:
        print(f"=== {sport.upper()} ===")
        sigs = get_test_signals(sport, clob, OPTIMAL[sport])
        if sigs.empty:
            print("  no signals\n"); continue
        print(f"  Total test signals: {len(sigs):,}")
        print()
        print("  Rank-in-market (1st signal first in time):")
        for r in consensus_lag_test(sigs) or []:
            sign = "+" if r["pnl"]>=0 else "-"
            print(f"    rank={str(r['rank']):<4}  n={r['n']:>5,}  "
                  f"WR={r['wr']:>5.1f}%  PnL={sign}${abs(r['pnl']):>6,.0f}  "
                  f"ROI={r['roi']:>+6.2f}%")
        print()
        print("  Lag-from-first-signal-in-market:")
        for r in lag_test(sigs) or []:
            sign = "+" if r["pnl"]>=0 else "-"
            print(f"    {r['lag_bucket']:<14}  n={r['n']:>5,}  "
                  f"WR={r['wr']:>5.1f}%  PnL={sign}${abs(r['pnl']):>6,.0f}  "
                  f"ROI={r['roi']:>+6.2f}%")
        print()


if __name__ == "__main__":
    main()
