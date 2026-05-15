"""
Identify the active losing wallets to track for the live fade strategy.

Filters bottom-1000 from full historical to: still trading recently AND
losing on recent trades AND on CS2 markets specifically.

Output: cowork_snapshot/esports/fade_targets.json
"""
import json
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

    # CS2 only (the signal we validated)
    cs2 = df[df["game"] == "cs2"].copy()
    print(f"CS2 resolved trades: {len(cs2):,}")

    # Most recent 60 days of available data
    latest_ts = cs2["timestamp"].max()
    recent_cutoff = latest_ts - 60*24*3600
    recent = cs2[cs2["timestamp"] >= recent_cutoff]
    print(f"Recent 60d slice: {len(recent):,} trades ending {pd.Timestamp(latest_ts, unit='s').date()}")

    g = recent.groupby("proxyWallet").agg(
        trades=("pnl", "size"),
        wins=("won", "sum"),
        pnl=("pnl", "sum"),
        total_volume_usd=("size", "sum"),
        last_ts=("timestamp", "max"),
    ).reset_index()
    g["wr"] = (g["wins"] / g["trades"] * 100).round(2)
    g["roi"] = (g["pnl"] / (g["trades"] * BET) * 100).round(2)
    g["avg_pnl"] = (g["pnl"] / g["trades"]).round(3)

    # Filter: meaningful sample (n>=30), losing (roi < -5%), recent (last 14d)
    very_recent = latest_ts - 14*24*3600
    targets = g[
        (g["trades"] >= 30) &
        (g["roi"] < -5) &
        (g["last_ts"] >= very_recent)
    ].sort_values("pnl").reset_index(drop=True)

    print(f"\nActive losing CS2 wallets (n>=30, ROI<-5%, traded in last 14d):")
    print(f"  count: {len(targets)}")
    print(f"\nTop 20 worst (best fade targets):")
    print(targets.head(20)[
        ["proxyWallet", "trades", "wr", "pnl", "roi", "avg_pnl"]
    ].to_string(index=False))

    out = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "data_through": pd.Timestamp(latest_ts, unit="s").isoformat(),
        "target_wallets": targets.head(500)["proxyWallet"].tolist(),
        "target_meta": targets.head(500).to_dict(orient="records"),
    }
    path = ES_DIR / "fade_targets.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved {len(out['target_wallets'])} target wallets: {path}")


if __name__ == "__main__":
    main()
