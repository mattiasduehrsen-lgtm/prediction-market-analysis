"""Quick per-game fade-bottom-1000 evaluation on the fresh 4M-trade dataset.

Splits 70/30 train/test, ranks bottom-1000 by train PnL, evaluates fade on
test slice for each game separately.
"""
import glob
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"
BET = 5.0


def determine_won(df):
    sell_mask = df["side"] == "SELL"
    return np.where(
        sell_mask,
        df["outcome"] != df["winning_outcome"],
        df["outcome"] == df["winning_outcome"],
    ).astype(bool)


def pnl_for_price(price, won, bet=BET):
    p = np.clip(price.astype(float), 0.05, 0.95)
    s = bet / p
    return np.where(won, s - bet, -bet)


def fade_pnl(t):
    if not len(t):
        return 0, 0.0, 0.0, 0.0
    t = t.copy()
    t["faded_won"] = ~t["won"]
    t["our_price"] = 1 - t["price"].astype(float)
    t["our_pnl"]   = pnl_for_price(t["our_price"], t["faded_won"].values)
    n = len(t)
    wr  = t["faded_won"].mean() * 100
    pnl = t["our_pnl"].sum()
    roi = pnl / (n * BET) * 100
    return n, wr, pnl, roi


def main():
    print("Loading...")
    shards = sorted(glob.glob(str(ES_DIR / "scrape" / "shards" / "*.parquet")))
    df = pd.concat([pd.read_parquet(s) for s in shards], ignore_index=True)
    res = pd.read_parquet(ES_DIR / "resolutions.parquet")[
        ["condition_id", "winning_outcome", "resolved", "slug"]
    ].rename(columns={"condition_id": "conditionId", "slug": "mkt_slug"})
    df = df.merge(res, on="conditionId", how="left")
    df = df[df["resolved"] & df["winning_outcome"].notna()].copy()
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df["won"] = determine_won(df)
    df["pnl"] = pnl_for_price(df["price"], df["won"].values)
    df["game"] = df["mkt_slug"].fillna("").str.split("-").str[0]

    split = int(len(df) * 0.7)
    train, test = df.iloc[:split], df.iloc[split:].copy()

    # Identify recently-active losers per game (n>=30 in 60d of train, ROI<-5%, last 14d)
    games_to_test = ["cs2", "league", "valorant", "dota", "ewc"]
    print("\n=== Per-game fade-bottom on TEST (active losers from train) ===")
    print(f"{'game':>10} {'targets':>8} {'test_trades':>12} {'WR%':>7} {'PnL':>14} {'ROI%':>8}")

    for g in games_to_test:
        # Filter game subset
        g_train = train[train["game"] == g]
        g_test  = test[test["game"] == g]
        if not len(g_train) or not len(g_test):
            print(f"{g:>10}  no data")
            continue

        # Identify losing wallets within this game
        agg = g_train.groupby("proxyWallet").agg(
            trades=("pnl", "size"),
            pnl=("pnl", "sum"),
            last_ts=("timestamp", "max"),
        ).reset_index()
        cutoff = g_train["timestamp"].max() - 30*24*3600
        agg = agg[(agg["trades"] >= 30) & (agg["pnl"] < 0) & (agg["last_ts"] >= cutoff)]
        agg = agg.sort_values("pnl", ascending=True)
        targets = set(agg.head(1000)["proxyWallet"])

        target_test = g_test[g_test["proxyWallet"].isin(targets)]
        n, wr, pnl, roi = fade_pnl(target_test)
        print(f"{g:>10} {len(targets):>8,} {n:>12,} {wr:>6.1f}% ${pnl:>+12,.0f} {roi:>+7.2f}%")


if __name__ == "__main__":
    main()
