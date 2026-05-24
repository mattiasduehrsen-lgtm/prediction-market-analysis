"""Per-market-type OOS ROI breakdown.

Sports markets come in different flavors:
  - moneyline (who wins straight up)
  - spread / handicap (team beats by X)
  - total over/under (combined score)
  - props (player or game-specific)

Do all market types fade equally well, or is one structure better than others?
This is critical for refining what to actually trade.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
SPORTS = ["nba", "mlb", "tennis", "nhl"]  # skip soccer
BET_USD = 5.0
SLIPPAGE = 0.01

# Best per-sport config from sweep
OPTIMAL = {
    "nhl":    {"min_trades": 30, "min_roi": -15.0, "min_entry": 0.70},
    "nba":    {"min_trades": 30, "min_roi": -30.0, "min_entry": 0.40},
    "mlb":    {"min_trades": 50, "min_roi": -30.0, "min_entry": 0.40},
    "tennis": {"min_trades": 50, "min_roi": -15.0, "min_entry": 0.50},
}


def classify_market_type(slug):
    s = (slug or "").lower()
    if "moneyline" in s or "winner" in s:
        return "moneyline"
    # Slug pattern usually: sport-team1-team2-DATE[-modifier]
    # Modifiers indicate type
    if "spread" in s or "handicap" in s or "-line-" in s or "pt5" in s and "spread" in s:
        return "spread/handicap"
    if "total" in s or "-over-" in s or "-under-" in s:
        return "total"
    if "set-handicap" in s or "set-spread" in s:
        return "spread/handicap"
    if "prop" in s or "first" in s or "scorer" in s or "player" in s:
        return "prop"
    # Base case: slug is just "sport-team1-team2-DATE" (no modifier) = moneyline
    parts = s.split("-")
    if len(parts) <= 4:
        return "moneyline"
    # Has modifier we don't recognize
    return "other"


def build_winner_map(clob_df, cids):
    sub = clob_df[clob_df["condition_id"].isin(cids)]
    w = {}
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try: tl = list(tokens)
        except: continue
        ws = [t for t in tl if isinstance(t, dict) and t.get("winner")]
        if len(ws) == 1: w[row["condition_id"]] = ws[0].get("outcome","")
    return w


def analyze(sport, clob_df, cfg):
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

    # Need slug column for market-type classification. Use the _slug field
    # added during scrape (or fall back to a 'slug' column if present)
    slug_col = None
    for c in trades.columns:
        if c.lower() == "_slug" or c.lower() == "slug":
            slug_col = c
            break

    all_cids = list(set(train["conditionId"]).union(set(test["conditionId"])))
    winners = build_winner_map(clob_df, all_cids)

    # cid -> slug map from clob (more reliable)
    sub = clob_df[clob_df["condition_id"].isin(all_cids)]
    cid_slug = dict(zip(sub["condition_id"], sub["slug"]))

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
    target_wallets = set(ts[(ts["trades"]>=cfg["min_trades"])
                             & (ts["roi"]<=cfg["min_roi"])].index)

    # cid_outs map
    cid_outs = {}
    for _, row in sub.iterrows():
        tokens = row.get("tokens")
        if tokens is None: continue
        try:
            tl = list(tokens)
            outs = [t.get("outcome") for t in tl if isinstance(t, dict)]
            if len(outs)==2 and all(outs):
                cid_outs[row["condition_id"]] = outs
        except: pass

    # Test simulation grouped by market type
    test_buys = test[(test["side"].str.upper()=="BUY")
                      & (test["proxyWallet"].isin(target_wallets))]

    by_type = defaultdict(lambda: {"n":0,"w":0,"l":0,"pnl":0.0,"cost":0.0})
    for r in test_buys.itertuples(index=False):
        cid = r.conditionId
        outs = cid_outs.get(cid)
        if not outs or r.outcome not in outs: continue
        our_out = [o for o in outs if o!=r.outcome][0]
        our_entry = round(1 - float(r.price) + SLIPPAGE, 4)
        if our_entry < cfg["min_entry"]: continue
        win = winners.get(cid)
        if win is None: continue
        slug = cid_slug.get(cid, "")
        mtype = classify_market_type(slug)
        won = (our_out == win)
        cost = BET_USD
        pnl = (BET_USD/our_entry)-cost if won else -cost
        by_type[mtype]["n"] += 1
        by_type[mtype]["pnl"] += pnl
        by_type[mtype]["cost"] += cost
        if won: by_type[mtype]["w"] += 1
        else: by_type[mtype]["l"] += 1

    return {sport: dict(by_type)}


def main():
    print("=" * 86)
    print(" PER-MARKET-TYPE OOS BREAKDOWN")
    print("   At each sport's optimal config, split test PnL by market type")
    print("=" * 86)
    print()

    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")

    all_data = {}
    for sport in SPORTS:
        print(f"=== {sport.upper()} ===")
        r = analyze(sport, clob, OPTIMAL[sport])
        if r is None: continue
        all_data.update(r)
        by_type = r[sport]
        print(f"  {'market type':<18} {'n':>6} {'W/L':>10} {'WR':>6} {'PnL':>9} {'ROI':>8}")
        # Sort by PnL desc
        for mtype, v in sorted(by_type.items(), key=lambda x: -x[1]["pnl"]):
            if v["n"] < 10: continue
            wr = v["w"]/max(v["n"],1)*100
            roi = v["pnl"]/max(v["cost"],1)*100
            sign = "+" if v["pnl"]>=0 else "-"
            print(f"  {mtype:<18} {v['n']:>6} {v['w']:>4}/{v['l']:<4} {wr:>5.1f}% "
                  f"{sign}${abs(v['pnl']):>6,.0f} {roi:>+6.2f}%")
        print()

    # Combined view by market type across sports
    print("=" * 86)
    print(" COMBINED: market type across all sports (NBA+MLB+Tennis+NHL)")
    print("=" * 86)
    combined = defaultdict(lambda: {"n":0,"w":0,"l":0,"pnl":0.0,"cost":0.0})
    for sport, by_type in all_data.items():
        for mtype, v in by_type.items():
            for k in ("n","w","l","pnl","cost"): combined[mtype][k] += v[k]
    print(f"  {'market type':<18} {'n':>6} {'W/L':>10} {'WR':>6} {'PnL':>9} {'ROI':>8}")
    for mtype, v in sorted(combined.items(), key=lambda x: -x[1]["pnl"]):
        if v["n"] < 50: continue
        wr = v["w"]/max(v["n"],1)*100
        roi = v["pnl"]/max(v["cost"],1)*100
        sign = "+" if v["pnl"]>=0 else "-"
        print(f"  {mtype:<18} {v['n']:>6} {v['w']:>4}/{v['l']:<4} {wr:>5.1f}% "
              f"{sign}${abs(v['pnl']):>6,.0f} {roi:>+6.2f}%")

    # Save
    out = COWORK / "sports_market_type_breakdown.json"
    out.write_text(json.dumps({"per_sport": all_data, "combined": dict(combined)},
                              indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
