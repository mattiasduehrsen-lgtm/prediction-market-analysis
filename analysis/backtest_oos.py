"""
Out-of-sample backtest with strict chronological train/test split.

1. Split trades chronologically: first 70% = TRAIN, last 30% = TEST
2. Rank wallets using ONLY train data
3. For each top-N selection (10, 50, 200, 1000 wallets), evaluate
   copy-trade performance on the held-out TEST data
4. Same for fade-bottom strategies

This eliminates the survivor-selection bias in the naive backtest.

If follow-whales is real, OOS performance should still be positive at
plausible-but-lower numbers. If it's purely selection bias, OOS will
collapse to ~chance.
"""
import glob, json
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"
BET = 5.0


def load_all():
    shards = sorted(glob.glob(str(ES_DIR / "scrape" / "shards" / "*.parquet")))
    df = pd.concat([pd.read_parquet(s) for s in shards], ignore_index=True)
    res = pd.read_parquet(ES_DIR / "resolutions.parquet")[
        ["condition_id", "winning_outcome", "resolved"]
    ].rename(columns={"condition_id": "conditionId"})
    df = df.merge(res, on="conditionId", how="left")
    df = df[df["resolved"] & df["winning_outcome"].notna()].copy()
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def determine_won(df):
    """For each row, did this trade win?

    A trade with outcome=X side=BUY wins if winner==X.
    A trade with outcome=X side=SELL wins if winner!=X (sold to opposite).
    """
    eff = df["outcome"].where(df["side"] == "BUY", None)
    sell_mask = df["side"] == "SELL"
    # For SELLs: the trader is exiting a position OR going short.
    # Simplest interpretation: SELL of X = bet against X = wins if winner!=X
    eff = eff.where(~sell_mask, "__NOT__")
    won = np.where(
        sell_mask,
        df["outcome"] != df["winning_outcome"],
        df["outcome"] == df["winning_outcome"],
    )
    return won.astype(bool)


def pnl_for_price(price, won, bet=BET):
    """
    Realistic PnL: clip price to [0.05, 0.95] to model real-world tradeability
    (sub-5c orders rarely have depth; >95c shares are essentially-resolved).
    """
    price = np.clip(price.astype(float), 0.05, 0.95)
    shares = bet / price
    return np.where(won, shares - bet, -bet)


def main():
    print("Loading...")
    df = load_all()
    print(f"  resolved trade rows: {len(df):,}")
    df["won"] = determine_won(df)
    df["pnl"] = pnl_for_price(df["price"], df["won"].values)

    n = len(df)
    split = int(n * 0.7)
    train = df.iloc[:split].copy()
    test  = df.iloc[split:].copy()
    print(f"  TRAIN: {len(train):,} trades  ({train.iloc[0]['timestamp']} -> {train.iloc[-1]['timestamp']})")
    print(f"  TEST:  {len(test):,} trades   ({test.iloc[0]['timestamp']} -> {test.iloc[-1]['timestamp']})")

    # Rank wallets using TRAIN only
    g = train.groupby("proxyWallet").agg(
        trades=("pnl", "size"),
        wins=("won", "sum"),
        pnl=("pnl", "sum"),
    ).reset_index()
    g["wr"] = g["wins"] / g["trades"]
    g["roi"] = g["pnl"] / (g["trades"] * BET)
    g["avg_pnl"] = g["pnl"] / g["trades"]
    # Require min sample
    g = g[g["trades"] >= 20]
    g = g.sort_values("pnl", ascending=False).reset_index(drop=True)
    print(f"  TRAIN wallets (>=20 trades): {len(g):,}")

    print("\n=== Out-of-sample: copy TOP-N wallets ===")
    print(f"{'N':>6} {'test trades':>13} {'WR%':>7} {'avg_pnl':>10} {'total_pnl':>12} {'ROI%':>8}")
    results_top = []
    for top_n in [10, 50, 100, 200, 500, 1000, 2000]:
        if top_n > len(g): continue
        wallets = set(g.head(top_n)["proxyWallet"].tolist())
        copy = test[test["proxyWallet"].isin(wallets)]
        if not len(copy): continue
        n_t = len(copy); wr = copy["won"].mean()*100
        avg = copy["pnl"].mean(); tot = copy["pnl"].sum()
        roi = tot / (n_t * BET) * 100
        print(f"{top_n:>6} {n_t:>13,} {wr:>6.2f}% {avg:>+10.3f} {tot:>+12,.0f} {roi:>+7.2f}%")
        results_top.append({"top_n": top_n, "test_trades": n_t, "wr_pct": wr, "avg_pnl": avg, "total_pnl": tot, "roi_pct": roi})

    print("\n=== Out-of-sample: FADE BOTTOM-N wallets ===")
    g_bottom = g.sort_values("pnl", ascending=True).reset_index(drop=True)
    print(f"{'N':>6} {'test trades':>13} {'fade WR%':>10} {'avg_pnl':>10} {'total_pnl':>12} {'ROI%':>8}")
    results_bot = []
    for bot_n in [10, 50, 100, 200, 500, 1000]:
        if bot_n > len(g_bottom): continue
        wallets = set(g_bottom.head(bot_n)["proxyWallet"].tolist())
        target = test[test["proxyWallet"].isin(wallets)].copy()
        if not len(target): continue
        # Fade: we win when they lose
        target["faded_won"] = ~target["won"]
        # Our entry price = 1 - their price (we buy the opposite side)
        target["our_price"] = 1 - target["price"].astype(float)
        target["our_pnl"]   = pnl_for_price(target["our_price"], target["faded_won"].values)
        n_t = len(target); wr = target["faded_won"].mean()*100
        avg = target["our_pnl"].mean(); tot = target["our_pnl"].sum()
        roi = tot / (n_t * BET) * 100
        print(f"{bot_n:>6} {n_t:>13,} {wr:>9.2f}% {avg:>+10.3f} {tot:>+12,.0f} {roi:>+7.2f}%")
        results_bot.append({"bot_n": bot_n, "test_trades": n_t, "wr_pct": wr, "avg_pnl": avg, "total_pnl": tot, "roi_pct": roi})

    # Save
    out = ES_DIR / "backtest_oos_results.json"
    out.write_text(json.dumps({"copy_top": results_top, "fade_bottom": results_bot}, indent=2))
    print(f"\nSaved: {out}")

    # Verdict
    print("\n=== Verdict ===")
    best_top = max(results_top, key=lambda r: r["roi_pct"]) if results_top else None
    best_bot = max(results_bot, key=lambda r: r["roi_pct"]) if results_bot else None
    if best_top and best_top["roi_pct"] > 2:
        print(f"COPY TOP signal: {best_top['top_n']} wallets -> ROI {best_top['roi_pct']:+.2f}% on {best_top['test_trades']:,} trades")
    if best_bot and best_bot["roi_pct"] > 2:
        print(f"FADE BOTTOM signal: {best_bot['bot_n']} wallets -> ROI {best_bot['roi_pct']:+.2f}% on {best_bot['test_trades']:,} trades")
    if (not best_top or best_top["roi_pct"] <= 2) and (not best_bot or best_bot["roi_pct"] <= 2):
        print("Neither strategy clears 2% ROI OOS — likely no clean signal from wallet copy.")


if __name__ == "__main__":
    main()
