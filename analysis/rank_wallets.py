"""
For each trader wallet, compute realized PnL and statistical edge.

Identifies "smart money" wallets we may want to copy-trade.

Output: cowork_snapshot/esports/wallet_ranking.parquet
"""
import glob
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"


def main():
    shards = sorted(glob.glob(str(ES_DIR / "scrape" / "shards" / "*.parquet")))
    print(f"Loading {len(shards)} shards...")
    df = pd.concat([pd.read_parquet(s) for s in shards], ignore_index=True)
    print(f"Total trades: {len(df):,}")

    # Resolutions
    res = pd.read_parquet(ES_DIR / "resolutions.parquet")[
        ["condition_id", "winning_outcome", "resolved"]
    ].rename(columns={"condition_id": "conditionId"})
    df = df.merge(res, on="conditionId", how="left")

    # Only resolved markets — others have unknown outcome
    df = df[df["resolved"] & df["winning_outcome"].notna()].copy()
    print(f"Trades on resolved markets: {len(df):,}")

    # Determine if this trade was on the winning side
    # Polymarket binary outcomes: "Yes" / "No". A BUY on "Yes" wins if winner=="Yes".
    # A SELL on "Yes" is effectively buying "No" → wins if winner=="No".
    def trade_won(row):
        outcome = row["outcome"]  # "Yes" or "No" — what side the row bought
        side = row["side"]        # "BUY" or "SELL"
        winner = row["winning_outcome"]
        # SELL means they're selling exposure on this outcome
        effective_outcome = outcome if side == "BUY" else ("No" if outcome == "Yes" else "Yes")
        return effective_outcome == winner

    df["won"] = df.apply(trade_won, axis=1)

    # Per-trade PnL (approximate):
    # BUY: paid price*size, redeemed for size if won else 0
    # SELL: received price*size, owed size if lost (i.e. position resolved against)
    def trade_pnl(row):
        size = float(row["size"] or 0)
        price = float(row["price"] or 0)
        if row["side"] == "BUY":
            return (size - price * size) if row["won"] else (-price * size)
        else:  # SELL — closed long: profit = received - cost basis 0 if won (unknown cost basis)
            # Best approximation: SELL @ price * size, settles at 0 if won, at size if lost
            return (price * size) if row["won"] else (price * size - size)
    df["est_pnl"] = df.apply(trade_pnl, axis=1)

    # Aggregate per wallet
    g = df.groupby("proxyWallet").agg(
        trades=("est_pnl", "size"),
        wins=("won", "sum"),
        total_pnl=("est_pnl", "sum"),
        total_volume=("size", "sum"),
        unique_markets=("conditionId", "nunique"),
        first_trade=("timestamp", "min"),
        last_trade=("timestamp", "max"),
    ).reset_index()
    g["wr_pct"] = (g["wins"] / g["trades"] * 100).round(2)
    g["avg_pnl"] = (g["total_pnl"] / g["trades"]).round(3)
    g["roi_pct"] = (g["total_pnl"] / g["total_volume"] * 100).round(2)
    g = g.sort_values("total_pnl", ascending=False).reset_index(drop=True)

    g.to_parquet(ES_DIR / "wallet_ranking.parquet", index=False)
    print(f"\nWallets: {len(g):,}")

    # Filter to meaningful sample sizes
    meaningful = g[(g["trades"] >= 20) & (g["unique_markets"] >= 5)]
    print(f"With >=20 trades on >=5 markets: {len(meaningful):,}")

    print("\nTop 15 most profitable (min 20 trades):")
    print(meaningful.head(15)[
        ["proxyWallet", "trades", "wins", "wr_pct", "total_pnl", "avg_pnl", "roi_pct", "unique_markets"]
    ].to_string(index=False))

    print("\nBottom 10 (whales we may want to fade):")
    print(meaningful.tail(10)[
        ["proxyWallet", "trades", "wr_pct", "total_pnl", "avg_pnl", "roi_pct"]
    ].to_string(index=False))


if __name__ == "__main__":
    main()
