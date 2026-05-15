"""
Validate the fade-bottom signal across time, game, and active-wallet filters.

Tests:
  1. Temporal stability: split test set into 3 chronological quarters,
     check that fade-bottom is profitable in EACH.
  2. Active-only: only fade wallets that traded in the most recent 30 days
     of train data (avoid copying dead wallets).
  3. Per-game breakout: CS2 vs LoL vs Valorant vs Dota — is signal in all
     or concentrated in one?
  4. Whale activity recency: is the signal recent? Did losing whales stop
     losing in 2026?
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
    won = np.where(
        sell_mask,
        df["outcome"] != df["winning_outcome"],
        df["outcome"] == df["winning_outcome"],
    )
    return won.astype(bool)


def pnl_for_price(price, won, bet=BET):
    price = np.clip(price.astype(float), 0.05, 0.95)
    shares = bet / price
    return np.where(won, shares - bet, -bet)


def load_all():
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
    return df


def rank_bottom_wallets(df, top_n=1000, min_trades=20):
    g = df.groupby("proxyWallet").agg(
        trades=("pnl", "size"), pnl=("pnl", "sum"),
        last_ts=("timestamp", "max"),
    ).reset_index()
    g = g[g["trades"] >= min_trades].sort_values("pnl", ascending=True)
    return g.head(top_n)


def fade_pnl(target_trades):
    if not len(target_trades): return 0, 0, 0.0, 0.0
    t = target_trades.copy()
    t["faded_won"] = ~t["won"]
    t["our_price"] = 1 - t["price"].astype(float)
    t["our_pnl"] = pnl_for_price(t["our_price"], t["faded_won"].values)
    n = len(t)
    wr = t["faded_won"].mean()*100
    pnl = t["our_pnl"].sum()
    roi = pnl / (n * BET) * 100
    return n, wr, pnl, roi


def main():
    df = load_all()
    print(f"Loaded {len(df):,} resolved trades")

    split = int(len(df) * 0.7)
    train, test = df.iloc[:split], df.iloc[split:].copy()
    print(f"Train: {len(train):,} | Test: {len(test):,}")

    # Test 1: temporal stability in test set
    print("\n=== TEST 1: temporal stability of fade-bottom-1000 ===")
    bottom = rank_bottom_wallets(train, top_n=1000)
    wallets = set(bottom["proxyWallet"])
    # Split test into 3 quarters
    test_sorted = test.sort_values("timestamp").reset_index(drop=True)
    qsize = len(test_sorted) // 3
    for i, (lo, hi) in enumerate([(0, qsize), (qsize, 2*qsize), (2*qsize, len(test_sorted))]):
        chunk = test_sorted.iloc[lo:hi]
        target = chunk[chunk["proxyWallet"].isin(wallets)]
        n, wr, pnl, roi = fade_pnl(target)
        ts_lo = pd.Timestamp(test_sorted.iloc[lo]["timestamp"], unit="s")
        ts_hi = pd.Timestamp(test_sorted.iloc[hi-1]["timestamp"], unit="s")
        print(f"  Q{i+1} ({ts_lo.date()} -> {ts_hi.date()}): n={n:,}  WR={wr:.1f}%  PnL=${pnl:+,.0f}  ROI={roi:+.2f}%")

    # Test 2: active-only — only wallets that traded in the last 30 days of TRAIN
    print("\n=== TEST 2: active-only (wallet last trade within 30d of train end) ===")
    train_end_ts = train["timestamp"].max()
    cutoff = train_end_ts - 30*24*3600
    bottom_active = bottom[bottom["last_ts"] >= cutoff]
    wallets_active = set(bottom_active["proxyWallet"])
    target_a = test[test["proxyWallet"].isin(wallets_active)]
    n, wr, pnl, roi = fade_pnl(target_a)
    print(f"  active wallets: {len(wallets_active)} / 1000")
    print(f"  test fade: n={n:,}  WR={wr:.1f}%  PnL=${pnl:+,.0f}  ROI={roi:+.2f}%")

    # Test 3: per-game breakout (use slug prefix)
    print("\n=== TEST 3: per-game breakout (fade bottom-1000) ===")
    target = test[test["proxyWallet"].isin(wallets)].copy()
    target["game"] = target["mkt_slug"].fillna("").str.split("-").str[0]
    for game in ("cs2","csgo","valorant","dota","league"):
        g = target[target["game"].isin([game, game[:3]])]
        if not len(g): continue
        n, wr, pnl, roi = fade_pnl(g)
        print(f"  {game:>10}: n={n:>6,}  WR={wr:.1f}%  PnL=${pnl:+,.0f}  ROI={roi:+.2f}%")

    # Test 4: signal recency — does fading STILL work on the very last 10% of test?
    print("\n=== TEST 4: most recent 10% of test ===")
    tail = test_sorted.iloc[int(len(test_sorted)*0.9):]
    target_tail = tail[tail["proxyWallet"].isin(wallets)]
    n, wr, pnl, roi = fade_pnl(target_tail)
    ts_lo = pd.Timestamp(tail.iloc[0]["timestamp"], unit="s")
    ts_hi = pd.Timestamp(tail.iloc[-1]["timestamp"], unit="s")
    print(f"  ({ts_lo.date()} -> {ts_hi.date()}): n={n:,}  WR={wr:.1f}%  PnL=${pnl:+,.0f}  ROI={roi:+.2f}%")

    # How many of the bottom-1000 are still active in most recent quarter?
    recent = test_sorted.iloc[int(len(test_sorted)*0.75):]
    active_recent = set(recent["proxyWallet"]) & wallets
    print(f"\n  Bottom-1000 still trading in latest 25% of test: {len(active_recent)}")


if __name__ == "__main__":
    main()
