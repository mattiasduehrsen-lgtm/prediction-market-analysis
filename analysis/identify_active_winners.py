"""
Identify the active winning wallets to COPY (follow-top strategy).

Counterpart to identify_active_targets.py — instead of bottom-N losers,
ranks the top wallets by realized PnL on recent resolved trades. The bot
then copies their trades instead of fading them.

Backtest signal: copy-top-10 wallets in CS2 = +255% ROI OOS on 9.5k trades.

Output: cowork_snapshot/esports/follow_targets.json
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

    GAMES = ["cs2", "league"]
    sub = df[df["game"].isin(GAMES)].copy()
    print(f"Resolved trades in {GAMES}: {len(sub):,}")

    # Per-game windows — see identify_active_targets.py for rationale.
    # LoL is offseason-dormant so its data + recency cutoff must be generous.
    GAME_DATA_WINDOW_DAYS   = {"cs2":  60, "league": 240}
    GAME_RECENT_WINDOW_DAYS = {"cs2":  14, "league": 180}

    all_followers = []
    for game in GAMES:
        gdf_all = sub[sub["game"] == game]
        if not len(gdf_all):
            continue
        g_latest = gdf_all["timestamp"].max()
        data_cutoff   = g_latest - GAME_DATA_WINDOW_DAYS[game] * 86400
        recent_cutoff = g_latest - GAME_RECENT_WINDOW_DAYS[game] * 86400
        gdf = gdf_all[gdf_all["timestamp"] >= data_cutoff]

        g = gdf.groupby("proxyWallet").agg(
            trades=("pnl", "size"),
            wins=("won", "sum"),
            pnl=("pnl", "sum"),
            last_ts=("timestamp", "max"),
        ).reset_index()
        g["game"]    = game
        g["wr"]      = (g["wins"] / g["trades"] * 100).round(2)
        g["roi"]     = (g["pnl"] / (g["trades"] * BET) * 100).round(2)
        g["avg_pnl"] = (g["pnl"] / g["trades"]).round(3)

        # Stricter filter for winners: need genuine edge, not lucky variance.
        # Higher min-trades and positive ROI cutoff.
        min_trades = 50 if game == "cs2" else 25
        tg = g[(g["trades"] >= min_trades) & (g["roi"] > 5) & (g["last_ts"] >= recent_cutoff)]
        tg = tg.sort_values("pnl", ascending=False).reset_index(drop=True)
        print(f"\n[{game}] active winning wallets (n>={min_trades}, ROI>+5%, last 14d): {len(tg)}")
        print(tg.head(10)[["proxyWallet", "trades", "wr", "pnl", "roi", "avg_pnl"]].to_string(index=False))

        # Expanded follow set: CS2 top-50, LoL top-20. Backtest used top-10
        # for CS2 (+255% ROI); going to 50 trades off some edge per-wallet for
        # ~2x more signal volume to validate the strategy faster.
        per_game_cap = 50 if game == "cs2" else 20
        all_followers.append(tg.head(per_game_cap))

    if not all_followers:
        print("\nNo follow targets found — aborting")
        return
    followers = pd.concat(all_followers, ignore_index=True).sort_values("pnl", ascending=False).reset_index(drop=True)

    # Deduplicate
    seen = set()
    unique = []
    for _, r in followers.iterrows():
        if r["proxyWallet"] in seen:
            continue
        seen.add(r["proxyWallet"])
        unique.append(r["proxyWallet"])

    out = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "data_through": pd.Timestamp(latest_ts, unit="s").isoformat(),
        "games":          GAMES,
        "target_wallets": unique,
        "target_meta":    followers.to_dict(orient="records"),
    }
    # Atomic write
    import os
    path = ES_DIR / "follow_targets.json"
    tmp  = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)
    print(f"\nSaved {len(unique)} unique follow wallets across {GAMES}: {path}")


if __name__ == "__main__":
    main()
