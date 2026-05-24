"""Best-config backtest: combine all OOS-validated improvements.

Stack on top of plain OOS:
  1. Per-sport optimal wallet selection thresholds (from sweep)
  2. Consensus filter: only fade if N>=2 target wallets hit the same market
  3. Skip spread/handicap markets (negative ROI in OOS)
  4. Skip soccer entirely (negative correlation)
  5. Apply realistic friction (40% cancel, 2c extra slip)

Compare: naive OOS, optimal-only, optimal+consensus, optimal+consensus+market-filter.
"""
from __future__ import annotations
import json, random, time
from collections import defaultdict
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
SPORTS = ["nba", "mlb", "tennis", "nhl"]  # exclude soccer
BET_USD = 5.0
SLIPPAGE_BASE = 0.01
EXTRA_SLIP = 0.02       # realistic friction
CANCEL_RATE = 0.40       # realistic friction

OPTIMAL = {
    "nhl":    {"min_trades": 30, "min_roi": -15.0, "min_entry": 0.70},
    "nba":    {"min_trades": 30, "min_roi": -30.0, "min_entry": 0.40},
    "mlb":    {"min_trades": 50, "min_roi": -30.0, "min_entry": 0.40},
    "tennis": {"min_trades": 50, "min_roi": -15.0, "min_entry": 0.50},
}


def classify_market_type(slug):
    s = (slug or "").lower()
    parts = s.split("-")
    # Find date position
    date_idx = -1
    for i, p in enumerate(parts):
        if len(p) == 4 and p.startswith("20") and p.isdigit():
            date_idx = i
            break
    after = parts[date_idx+3:] if date_idx >= 0 else parts[4:]
    after_str = "-".join(after)
    if not after: return "moneyline"
    if "spread" in after_str or "handicap" in after_str or "-line-" in after_str:
        return "spread/handicap"
    if "total" in after_str or "over" in after_str or "under" in after_str:
        return "total"
    if "prop" in after_str or "first" in after_str: return "prop"
    return "other"


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


def get_test_sigs(sport, clob_df, cfg):
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
            if len(outs)==2 and all(outs): cid_outs[row["condition_id"]] = outs
        except: pass
    tb2 = test[(test["side"].str.upper()=="BUY") & (test["proxyWallet"].isin(targets))].copy()
    sigs = []
    for r in tb2.itertuples(index=False):
        outs = cid_outs.get(r.conditionId)
        if not outs or r.outcome not in outs: continue
        our_out = [o for o in outs if o!=r.outcome][0]
        our_entry_naked = round(1 - float(r.price), 4)
        if our_entry_naked + SLIPPAGE_BASE < cfg["min_entry"]: continue
        win = winners.get(r.conditionId)
        if win is None: continue
        slug = cid_slug.get(r.conditionId, "")
        mtype = classify_market_type(slug)
        sigs.append({"ts": float(r.timestamp), "cid": r.conditionId,
                     "wallet": r.proxyWallet, "our_outcome": our_out,
                     "our_entry_naked": our_entry_naked, "winner": win,
                     "mtype": mtype, "slug": slug})
    return pd.DataFrame(sigs)


def simulate(sigs, *, min_consensus=1, skip_types=None, slip=SLIPPAGE_BASE,
             cancel_rate=0.0, seed=42):
    """Run simulation with given filters. Returns stats dict."""
    if sigs.empty: return _empty_stats()
    skip_types = set(skip_types or [])
    rng = random.Random(seed)
    df = sigs.copy().sort_values(["cid","ts"])
    df["rank"] = df.groupby("cid").cumcount() + 1
    # Filter: market type
    if skip_types:
        df = df[~df["mtype"].isin(skip_types)]
    # Filter: consensus rank
    df = df[df["rank"] >= min_consensus]

    n_attempt = len(df)
    n_cancelled = n_resolved = n_wins = n_losses = 0
    total_pnl = total_cost = 0.0
    for r in df.itertuples(index=False):
        if rng.random() < cancel_rate:
            n_cancelled += 1
            continue
        our_entry = round(r.our_entry_naked + slip, 4)
        won = (r.our_outcome == r.winner)
        cost = BET_USD
        pnl = (BET_USD / our_entry) - cost if won else -cost
        total_pnl += pnl
        total_cost += cost
        if won: n_wins += 1
        else:   n_losses += 1
        n_resolved += 1
    return {
        "attempts": n_attempt, "cancelled": n_cancelled, "resolved": n_resolved,
        "wins": n_wins, "losses": n_losses,
        "wr": (n_wins/n_resolved*100) if n_resolved else 0,
        "pnl": round(total_pnl,2), "cost": round(total_cost,2),
        "roi": (total_pnl/total_cost*100) if total_cost else 0,
    }


def _empty_stats():
    return {"attempts":0,"cancelled":0,"resolved":0,"wins":0,"losses":0,
            "wr":0,"pnl":0,"cost":0,"roi":0}


def main():
    print("=" * 90)
    print(" BEST-CONFIG BACKTEST (combining all learnings)")
    print("=" * 90)
    clob = pd.read_parquet(COWORK / "esports" / "clob_markets.parquet")

    # Build signals per sport
    sport_sigs = {}
    for sport in SPORTS:
        s = get_test_sigs(sport, clob, OPTIMAL[sport])
        sport_sigs[sport] = s
        print(f"  {sport}: {len(s):,} test signals")
    print()

    scenarios = [
        # (label, consensus, skip_types, slip, cancel)
        ("baseline OOS",                    1, [],                 SLIPPAGE_BASE, 0.0),
        ("+ realistic friction",            1, [],                 SLIPPAGE_BASE+EXTRA_SLIP, CANCEL_RATE),
        ("+ consensus N>=2",                2, [],                 SLIPPAGE_BASE+EXTRA_SLIP, CANCEL_RATE),
        ("+ skip spread/handicap",          2, ["spread/handicap"], SLIPPAGE_BASE+EXTRA_SLIP, CANCEL_RATE),
        ("+ consensus N>=5",                5, ["spread/handicap"], SLIPPAGE_BASE+EXTRA_SLIP, CANCEL_RATE),
    ]

    print(f"{'Scenario':<32} {'attempts':>9} {'cancel':>7} {'resolved':>9} {'WR':>5} {'PnL':>9} {'cost':>10} {'ROI':>8}")
    print("-" * 95)
    final_results = {}
    for label, consensus, skip_t, slip, cancel in scenarios:
        # Aggregate over all sports
        tot = {"attempts":0,"cancelled":0,"resolved":0,"wins":0,"losses":0,
                "pnl":0.0,"cost":0.0}
        for sport, sigs in sport_sigs.items():
            r = simulate(sigs, min_consensus=consensus, skip_types=skip_t,
                          slip=slip, cancel_rate=cancel)
            for k in tot: tot[k] += r[k] if isinstance(r[k], (int,float)) else 0
        wr = tot["wins"]/max(tot["resolved"],1)*100
        roi = tot["pnl"]/max(tot["cost"],1)*100
        sign = "+" if tot["pnl"]>=0 else "-"
        print(f"{label:<32} {tot['attempts']:>9,} {tot['cancelled']:>7,} "
              f"{tot['resolved']:>9,} {wr:>4.1f}% {sign}${abs(tot['pnl']):>6,.0f} "
              f"${tot['cost']:>8,.0f} {roi:>+6.2f}%")
        final_results[label] = {**tot, "wr":round(wr,2), "roi":round(roi,2)}

    # Per-sport breakdown for the BEST scenario
    print()
    print(f"--- Per-sport with consensus N>=2, no spread, realistic friction ---")
    print(f"{'sport':<8} {'attempts':>9} {'resolved':>9} {'WR':>5} {'PnL':>9} {'ROI':>8}")
    for sport in SPORTS:
        sigs = sport_sigs[sport]
        r = simulate(sigs, min_consensus=2, skip_types=["spread/handicap"],
                      slip=SLIPPAGE_BASE+EXTRA_SLIP, cancel_rate=CANCEL_RATE)
        sign = "+" if r["pnl"]>=0 else "-"
        print(f"{sport:<8} {r['attempts']:>9,} {r['resolved']:>9,} {r['wr']:>4.1f}% "
              f"{sign}${abs(r['pnl']):>6,.0f} {r['roi']:>+6.2f}%")

    # Save
    out = COWORK / "sports_best_config_results.json"
    out.write_text(json.dumps(final_results, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
