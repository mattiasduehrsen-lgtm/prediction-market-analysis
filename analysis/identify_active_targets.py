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

    # Games where per-game OOS backtest cleared ~+100% ROI on a real sample.
    # cs2: +144% ROI on 176k trades (1000 targets)
    # league: +127% ROI on 4,955 trades (109 targets)
    # dota/valorant samples too small to trust right now.
    GAMES = ["cs2", "league"]
    sub = df[df["game"].isin(GAMES)].copy()
    print(f"Resolved trades in {GAMES}: {len(sub):,}")

    # Most recent 60 days
    latest_ts = sub["timestamp"].max()
    recent_cutoff = latest_ts - 60 * 24 * 3600
    recent = sub[sub["timestamp"] >= recent_cutoff]
    print(f"Recent 60d slice: {len(recent):,} trades ending {pd.Timestamp(latest_ts, unit='s').date()}")

    # Rank wallets per-game (so a CS2 grinder and a LoL grinder can both appear)
    all_targets = []
    for game in GAMES:
        gdf = recent[recent["game"] == game]
        if not len(gdf):
            continue
        g = gdf.groupby("proxyWallet").agg(
            trades=("pnl", "size"),
            wins=("won", "sum"),
            pnl=("pnl", "sum"),
            total_volume_usd=("size", "sum"),
            last_ts=("timestamp", "max"),
        ).reset_index()
        g["game"]    = game
        g["wr"]      = (g["wins"] / g["trades"] * 100).round(2)
        g["roi"]     = (g["pnl"] / (g["trades"] * BET) * 100).round(2)
        g["avg_pnl"] = (g["pnl"] / g["trades"]).round(3)

        very_recent = latest_ts - 14 * 24 * 3600
        # Lower trade-count floor for LoL since its volume is much smaller
        min_trades = 30 if game == "cs2" else 15
        tg = g[(g["trades"] >= min_trades) & (g["roi"] < -5) & (g["last_ts"] >= very_recent)]
        tg = tg.sort_values("pnl").reset_index(drop=True)
        print(f"\n[{game}] active losing wallets (n>={min_trades}, ROI<-5%, last 14d): {len(tg)}")
        print(tg.head(10)[["proxyWallet", "trades", "wr", "pnl", "roi", "avg_pnl"]].to_string(index=False))
        # Top-K per game — CS2 gets 500, LoL gets 200 (smaller pool, fewer truly persistent losers)
        per_game_cap = 500 if game == "cs2" else 200
        all_targets.append(tg.head(per_game_cap))

    if not all_targets:
        print("\nNo targets found — aborting")
        return
    targets = pd.concat(all_targets, ignore_index=True).sort_values("pnl").reset_index(drop=True)

    # Deduplicate — a wallet active in multiple games appears once
    seen = set()
    unique_wallets = []
    for _, r in targets.iterrows():
        w = r["proxyWallet"]
        if w in seen:
            continue
        seen.add(w)
        unique_wallets.append(w)

    out = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "data_through": pd.Timestamp(latest_ts, unit="s").isoformat(),
        "games":          GAMES,
        "target_wallets": unique_wallets,
        "target_meta":    targets.to_dict(orient="records"),
    }
    # Atomic write: write to .tmp then os.replace() so the bot's hot-reload
    # never reads a partially-written JSON file.
    import os
    path = ES_DIR / "fade_targets.json"
    tmp  = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    print(f"\nSaved {len(unique_wallets)} unique target wallets across {GAMES}: {path}")


if __name__ == "__main__":
    main()
