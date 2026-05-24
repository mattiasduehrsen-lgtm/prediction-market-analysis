"""Risk profile of the consensus-filtered OOS strategy.

Critical questions before LIVE deployment:
  - What's the daily PnL distribution? (std, worst day, best day)
  - Max losing streak in consecutive trades?
  - Max drawdown in cumulative PnL?
  - At what bet size do bankroll requirements become uncomfortable?

Uses the OOS test signals with consensus filter (N>=2) + market filter
+ realistic friction applied.
"""
from __future__ import annotations
import datetime as dt
import random
from collections import defaultdict
from pathlib import Path
import pandas as pd
import statistics as stats

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
SPORTS = ["nba", "mlb", "tennis", "nhl"]
BET_USD = 5.0
SLIPPAGE_BASE = 0.01
EXTRA_SLIP = 0.02
CANCEL_RATE = 0.40
CONSENSUS_N = 2

OPTIMAL = {
    "nhl":    {"min_trades": 30, "min_roi": -15.0, "min_entry": 0.70},
    "nba":    {"min_trades": 30, "min_roi": -30.0, "min_entry": 0.40},
    "mlb":    {"min_trades": 50, "min_roi": -30.0, "min_entry": 0.40},
    "tennis": {"min_trades": 50, "min_roi": -15.0, "min_entry": 0.50},
}


def classify_market_type(slug):
    s = (slug or "").lower()
    parts = s.split("-")
    date_idx = -1
    for i, p in enumerate(parts):
        if len(p)==4 and p.startswith("20") and p.isdigit():
            date_idx = i; break
    after = parts[date_idx+3:] if date_idx>=0 else parts[4:]
    a = "-".join(after)
    if "spread" in a or "handicap" in a or "-line-" in a: return "spread/handicap"
    if "total" in a or "over" in a or "under" in a: return "total"
    return "moneyline" if not a else "other"


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


def get_filtered_signals(sport, clob_df, cfg):
    """Return list of (ts, pnl) tuples after all filters."""
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
    train = trades[trades["timestamp"]<train_end]
    test = trades[trades["timestamp"]>=train_end]

    all_cids = list(set(train["conditionId"]).union(set(test["conditionId"])))
    winners = build_winner_map(clob_df, all_cids)
    tb = train[train["side"].str.upper()=="BUY"].copy()
    tb["winner"] = tb["conditionId"].map(winners)
    res = tb.dropna(subset=["winner"]).copy()
    res["won"] = res["outcome"]==res["winner"]
    res["cost"] = res["price"]*res["size"]
    res["pnl"] = res.apply(lambda r: r["size"]-r["cost"] if r["won"] else -r["cost"], axis=1)
    ts = res.groupby("proxyWallet").agg(trades=("pnl","size"), pnl=("pnl","sum"), cost=("cost","sum"))
    ts["roi"] = ts["pnl"]/ts["cost"].clip(lower=0.01)*100
    targets = set(ts[(ts["trades"]>=cfg["min_trades"]) & (ts["roi"]<=cfg["min_roi"])].index)

    cid_outs = {}; cid_slug = {}
    sub = clob_df[clob_df["condition_id"].isin(all_cids)]
    for _, row in sub.iterrows():
        cid_slug[row["condition_id"]] = row["slug"]
        tokens = row.get("tokens")
        if tokens is None: continue
        try:
            tl = list(tokens)
            outs = [t.get("outcome") for t in tl if isinstance(t,dict)]
            if len(outs)==2 and all(outs):
                cid_outs[row["condition_id"]] = outs
        except: pass

    tb2 = test[(test["side"].str.upper()=="BUY") & (test["proxyWallet"].isin(targets))].copy()
    tb2 = tb2.sort_values(["conditionId","timestamp"])

    # Apply all filters
    rng = random.Random(42)
    consensus_count = defaultdict(set)
    signals = []
    for r in tb2.itertuples(index=False):
        outs = cid_outs.get(r.conditionId)
        if not outs or r.outcome not in outs: continue
        our_out = [o for o in outs if o!=r.outcome][0]
        our_entry = round(1 - float(r.price) + SLIPPAGE_BASE + EXTRA_SLIP, 4)
        if our_entry < cfg["min_entry"]: continue
        win = winners.get(r.conditionId)
        if win is None: continue
        # Market type filter
        slug = cid_slug.get(r.conditionId, "")
        if classify_market_type(slug) == "spread/handicap": continue
        # Consensus filter
        ckey = (r.conditionId, our_out)
        consensus_count[ckey].add(r.proxyWallet)
        if len(consensus_count[ckey]) < CONSENSUS_N: continue
        # Cancel filter
        if rng.random() < CANCEL_RATE: continue
        # Trade!
        won = (our_out == win)
        cost = BET_USD
        pnl = (BET_USD/our_entry) - cost if won else -cost
        signals.append({"ts": float(r.timestamp), "sport": sport, "pnl": pnl, "won": won})
    return signals


def main():
    print("=" * 80)
    print(" RISK / DRAWDOWN ANALYSIS")
    print("   Consensus-filtered OOS strategy at $5/trade, realistic friction")
    print("=" * 80)
    print()
    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")

    all_signals = []
    for s in SPORTS:
        sigs = get_filtered_signals(s, clob, OPTIMAL[s])
        print(f"  {s}: {len(sigs):,} filtered signals")
        all_signals.extend(sigs)
    all_signals.sort(key=lambda x: x["ts"])
    print(f"\nTotal: {len(all_signals):,} signals\n")

    # Daily aggregation
    by_day = defaultdict(lambda: {"n":0,"w":0,"l":0,"pnl":0.0})
    for s in all_signals:
        d = dt.datetime.fromtimestamp(s["ts"], tz=dt.timezone.utc).date().isoformat()
        b = by_day[d]
        b["n"] += 1
        b["pnl"] += s["pnl"]
        if s["won"]: b["w"] += 1
        else: b["l"] += 1

    days = sorted(by_day.keys())
    daily_pnls = [by_day[d]["pnl"] for d in days]
    print("Daily PnL distribution:")
    print(f"  Mean:     ${stats.mean(daily_pnls):+.2f}")
    print(f"  Median:   ${stats.median(daily_pnls):+.2f}")
    print(f"  Stdev:    ${stats.stdev(daily_pnls) if len(daily_pnls)>1 else 0:.2f}")
    print(f"  Best day: ${max(daily_pnls):+.2f}")
    print(f"  Worst day:${min(daily_pnls):+.2f}")
    print(f"\nDaily breakdown:")
    cum = 0
    for d in days:
        b = by_day[d]
        cum += b["pnl"]
        sign = "+" if b["pnl"]>=0 else "-"
        print(f"  {d}  n={b['n']:>4}  W/L={b['w']:>3}/{b['l']:<3}  "
              f"day=${b['pnl']:>+7.2f}  cum=${cum:>+7.2f}")

    # Max drawdown
    cum_curve = []; running = 0
    for s in all_signals:
        running += s["pnl"]; cum_curve.append(running)
    peak = cum_curve[0]; max_dd = 0
    for v in cum_curve:
        peak = max(peak, v)
        dd = peak - v
        if dd > max_dd: max_dd = dd
    print(f"\nMax drawdown across {len(cum_curve):,} trades: ${max_dd:.2f}")
    print(f"  (At $5/trade with $200 bankroll, this would be {max_dd/200*100:.0f}% drawdown)")
    print(f"  (At $5/trade with $1000 bankroll: {max_dd/1000*100:.1f}% drawdown)")

    # Consecutive losses
    streak = max_loss_streak = 0
    for s in all_signals:
        if s["won"]: streak = 0
        else:
            streak += 1
            max_loss_streak = max(max_loss_streak, streak)
    print(f"\nMax consecutive losses: {max_loss_streak}")
    print(f"  At $5/trade × {max_loss_streak} = ${max_loss_streak*5:.0f} worst-case streak")

    # Per-sport variance
    print(f"\nPer-sport contribution:")
    by_sport = defaultdict(lambda: [])
    for s in all_signals: by_sport[s["sport"]].append(s["pnl"])
    for sp, lst in sorted(by_sport.items(), key=lambda x: -sum(x[1])):
        total = sum(lst); n = len(lst)
        avg = total/n if n else 0
        std = stats.stdev(lst) if len(lst)>1 else 0
        print(f"  {sp:<8} n={n:>5,}  total=${total:>+7.2f}  avg/trade=${avg:>+6.3f}  std=${std:.2f}")

    print("\n" + "="*80)
    print(" PRACTICAL TAKEAWAYS FOR LIVE DEPLOYMENT")
    print("="*80)
    print(f"  • Daily PnL volatility (std): ${stats.stdev(daily_pnls) if len(daily_pnls)>1 else 0:.0f}")
    print(f"  • Worst observed day: ${min(daily_pnls):+.0f}")
    print(f"  • Max drawdown over 7d test: ${max_dd:.0f}")
    print(f"  • Max consecutive losses: {max_loss_streak} (= ${max_loss_streak*5:.0f} cash)")
    print(f"  • Recommended starting bankroll: ${max_dd*3:.0f} = 3x worst drawdown")
    print(f"  • Daily loss cap recommendation: ${-min(daily_pnls)*2:.0f} = 2x worst observed day")


if __name__ == "__main__":
    main()
