"""Time-of-day + day-of-week PnL patterns.

For NBA, MLB, Tennis (the sports with real edge), look at:
  - PnL by UTC hour-of-day
  - PnL by day-of-week
  - Are there windows we should pause or scale up?
"""
from __future__ import annotations
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
BET_USD = 5.0
SLIPPAGE = 0.01

OPTIMAL = {
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


def get_signals_with_pnl(sport, clob_df, cfg):
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
    ts = res.groupby("proxyWallet").agg(
        trades=("pnl","size"), pnl=("pnl","sum"), cost=("cost","sum"))
    ts["roi"] = ts["pnl"]/ts["cost"].clip(lower=0.01)*100
    targets = set(ts[(ts["trades"]>=cfg["min_trades"])
                      & (ts["roi"]<=cfg["min_roi"])].index)
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
    tb2 = test[(test["side"].str.upper()=="BUY")
                & (test["proxyWallet"].isin(targets))].copy()
    sigs = []
    for r in tb2.itertuples(index=False):
        outs = cid_outs.get(r.conditionId)
        if not outs or r.outcome not in outs: continue
        our_out = [o for o in outs if o!=r.outcome][0]
        our_entry = round(1 - float(r.price) + SLIPPAGE, 4)
        if our_entry < cfg["min_entry"]: continue
        win = winners.get(r.conditionId)
        if win is None: continue
        won = (our_out == win)
        pnl = (BET_USD/our_entry) - BET_USD if won else -BET_USD
        sigs.append({"ts": float(r.timestamp), "won": won, "pnl": pnl,
                     "our_entry": our_entry})
    return pd.DataFrame(sigs)


def hourly_breakdown(sigs):
    if sigs.empty: return None
    sigs = sigs.copy()
    sigs["hour"] = sigs["ts"].apply(
        lambda t: dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).hour)
    out = []
    for h in range(24):
        sub = sigs[sigs["hour"]==h]
        if len(sub) < 20: continue
        wr = sub["won"].mean()*100
        pnl = sub["pnl"].sum()
        roi = pnl / (len(sub)*BET_USD) * 100
        out.append({"hour": h, "n": len(sub), "wr": round(wr,1),
                    "pnl": round(pnl,2), "roi": round(roi,2)})
    return out


def dow_breakdown(sigs):
    if sigs.empty: return None
    sigs = sigs.copy()
    sigs["dow"] = sigs["ts"].apply(
        lambda t: dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).strftime("%a"))
    order = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    out = []
    for d in order:
        sub = sigs[sigs["dow"]==d]
        if len(sub) < 20: continue
        wr = sub["won"].mean()*100
        pnl = sub["pnl"].sum()
        roi = pnl / (len(sub)*BET_USD) * 100
        out.append({"dow": d, "n": len(sub), "wr": round(wr,1),
                    "pnl": round(pnl,2), "roi": round(roi,2)})
    return out


def main():
    print("=" * 80)
    print(" TIME-OF-DAY + DAY-OF-WEEK PATTERNS")
    print("=" * 80)
    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")
    for sport, cfg in OPTIMAL.items():
        print(f"\n=== {sport.upper()} ===")
        sigs = get_signals_with_pnl(sport, clob, cfg)
        if sigs.empty:
            print("  no signals"); continue
        print(f"  Total signals: {len(sigs):,}")
        print(f"\n  Hourly (UTC):")
        print(f"  {'hour':>5}  {'n':>5}  {'WR':>5}  {'PnL':>8}  {'ROI':>8}")
        for r in hourly_breakdown(sigs) or []:
            sign = "+" if r["pnl"]>=0 else "-"
            print(f"  {r['hour']:>5}  {r['n']:>5,}  {r['wr']:>4.1f}%  "
                  f"{sign}${abs(r['pnl']):>5.0f}  {r['roi']:>+6.2f}%")
        print(f"\n  Day-of-week:")
        for r in dow_breakdown(sigs) or []:
            sign = "+" if r["pnl"]>=0 else "-"
            print(f"  {r['dow']}  {r['n']:>5,}  {r['wr']:>4.1f}%  "
                  f"{sign}${abs(r['pnl']):>5.0f}  {r['roi']:>+6.2f}%")


if __name__ == "__main__":
    main()
