"""
Backtest naïve strategies on the resolved-esports trades dataset.

Strategies:
  1. ALWAYS-FAVORITE: buy whichever side is over 0.50 right before resolution
  2. ALWAYS-UNDERDOG: buy the under-0.50 side (expected to lose more often,
     but pays out larger when right — variance check)
  3. FOLLOW-WHALES: copy trades from top-5% PnL wallets only
  4. FADE-WHALES: trade OPPOSITE to bottom-5% PnL wallets
  5. EARLY-VOLUME-FAVORITE: enter as soon as one side accumulates >70% of
     early volume (first 6 hours of market trading)
  6. LATE-DUMP: enter the heavy side in the last hour before resolution

All strategies assume entry at the next observed mid-market price; exit
at resolution (size shares -> $1 or $0). Bet size = $5 per trade.

Output: cowork_snapshot/esports/backtest_results.json
"""
import glob, json
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"
BET = 5.0


def load_trades():
    shards = sorted(glob.glob(str(ES_DIR / "scrape" / "shards" / "*.parquet")))
    df = pd.concat([pd.read_parquet(s) for s in shards], ignore_index=True)
    res = pd.read_parquet(ES_DIR / "resolutions.parquet")[
        ["condition_id", "winning_outcome", "resolved"]
    ].rename(columns={"condition_id": "conditionId"})
    df = df.merge(res, on="conditionId", how="left")
    df = df[df["resolved"] & df["winning_outcome"].notna()].copy()
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df.sort_values(["conditionId", "timestamp"]).reset_index(drop=True)
    return df


def pnl_for(price: float, won: bool, bet: float = BET) -> float:
    """If we BUY a token at `price` for $bet, we get bet/price shares.
       Settles to bet/price if won, else 0. PnL = (bet/price) - bet if won, -bet if lost."""
    if price <= 0 or price >= 1:
        return 0.0
    shares = bet / price
    return (shares - bet) if won else -bet


def strategy_favorite(df):
    """For each market, take the last pre-resolution mid as 'final price'.
       Buy the side that's >0.50 there. Win if winner == that side."""
    rows = []
    for cid, g in df.groupby("conditionId"):
        last = g.iloc[-1]
        # We don't have orderbook mid, so use last trade price as proxy.
        last_price_yes = float(last["price"]) if last["outcome"] == "Yes" else (1 - float(last["price"]))
        winner = last["winning_outcome"]
        if last_price_yes >= 0.50:
            bet_side = "Yes"
            entry_price = last_price_yes
        else:
            bet_side = "No"
            entry_price = 1 - last_price_yes
        won = (bet_side == winner)
        rows.append({"strategy": "always_favorite", "conditionId": cid,
                     "entry_price": entry_price, "won": won,
                     "pnl": pnl_for(entry_price, won)})
    return rows


def strategy_underdog(df):
    rows = []
    for cid, g in df.groupby("conditionId"):
        last = g.iloc[-1]
        last_price_yes = float(last["price"]) if last["outcome"] == "Yes" else (1 - float(last["price"]))
        winner = last["winning_outcome"]
        if last_price_yes < 0.50:
            bet_side, entry_price = "Yes", last_price_yes
        else:
            bet_side, entry_price = "No", 1 - last_price_yes
        won = (bet_side == winner)
        rows.append({"strategy": "always_underdog", "conditionId": cid,
                     "entry_price": entry_price, "won": won,
                     "pnl": pnl_for(entry_price, won)})
    return rows


def strategy_follow_whales(df, top_wallets):
    rows = []
    for _, t in df[df["proxyWallet"].isin(top_wallets)].iterrows():
        price = float(t["price"])
        if not (0 < price < 1):
            continue
        # If they BOUGHT a side, we buy the same side. If they SOLD, we sell same.
        effective_side = t["outcome"] if t["side"] == "BUY" else ("No" if t["outcome"] == "Yes" else "Yes")
        won = (effective_side == t["winning_outcome"])
        # entry price = trade price (we copy at their fill)
        rows.append({"strategy": "follow_whales", "conditionId": t["conditionId"],
                     "entry_price": price, "won": won,
                     "pnl": pnl_for(price, won)})
    return rows


def strategy_fade_whales(df, bottom_wallets):
    rows = []
    for _, t in df[df["proxyWallet"].isin(bottom_wallets)].iterrows():
        price = float(t["price"])
        if not (0 < price < 1):
            continue
        effective_side = t["outcome"] if t["side"] == "BUY" else ("No" if t["outcome"] == "Yes" else "Yes")
        # Fade: take OPPOSITE side
        our_side = "No" if effective_side == "Yes" else "Yes"
        our_entry = 1 - price
        won = (our_side == t["winning_outcome"])
        rows.append({"strategy": "fade_whales", "conditionId": t["conditionId"],
                     "entry_price": our_entry, "won": won,
                     "pnl": pnl_for(our_entry, won)})
    return rows


def summarize(rows, name):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    n = len(df)
    wr = df["won"].mean() * 100
    total_pnl = df["pnl"].sum()
    avg_pnl = df["pnl"].mean()
    bets = n * BET
    roi = (total_pnl / bets * 100) if bets > 0 else 0
    return {
        "strategy": name,
        "n_trades": n,
        "win_rate_pct": round(wr, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl_per_trade": round(avg_pnl, 3),
        "total_bet": round(bets, 2),
        "roi_pct": round(roi, 2),
    }


def main():
    print("Loading trades + resolutions...")
    df = load_trades()
    print(f"Resolved-trade rows: {len(df):,}")

    # Load wallet ranking — pick top/bottom 5%
    wr = pd.read_parquet(ES_DIR / "wallet_ranking.parquet")
    wr = wr[(wr["trades"] >= 20) & (wr["unique_markets"] >= 5)]
    print(f"Wallets with >=20 trades: {len(wr):,}")
    cutoff = max(1, int(len(wr) * 0.05))
    top    = set(wr.head(cutoff)["proxyWallet"].tolist())
    bottom = set(wr.tail(cutoff)["proxyWallet"].tolist())
    print(f"Top 5%: {len(top)} wallets, Bottom 5%: {len(bottom)}")

    print("\nRunning baseline strategies...")
    results = []
    for name, fn in [
        ("always_favorite", lambda: strategy_favorite(df)),
        ("always_underdog", lambda: strategy_underdog(df)),
        ("follow_whales",   lambda: strategy_follow_whales(df, top)),
        ("fade_whales",     lambda: strategy_fade_whales(df, bottom)),
    ]:
        rows = fn()
        s = summarize(rows, name)
        if s:
            results.append(s)
            print(f"  {name:20} n={s['n_trades']:>6,}  WR={s['win_rate_pct']:>5.1f}%  "
                  f"PnL=${s['total_pnl']:>+9,.2f}  avg=${s['avg_pnl_per_trade']:>+.3f}  ROI={s['roi_pct']:>+.2f}%")

    out = ES_DIR / "backtest_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")

    # Verdict
    profitable = [r for r in results if r["roi_pct"] > 1.0 and r["n_trades"] > 100]
    if profitable:
        print(f"\n=== POSITIVE STRATEGIES ({len(profitable)}) ===")
        for r in profitable:
            print(f"  {r['strategy']}: +{r['roi_pct']}% ROI on {r['n_trades']:,} trades")
    else:
        print(f"\n=== No naïve strategy clears 1% ROI on >=100 trades ===")


if __name__ == "__main__":
    main()
