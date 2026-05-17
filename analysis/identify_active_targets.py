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

    # Per-game recency windows. Each game uses its OWN latest_ts so an off-season
    # game (like LoL between Worlds and MSI) still produces a usable target list
    # — its wallets will fire when the next tournament starts and they resume
    # trading. CS2 trades 24/7 so its window stays tight; LoL/Dota get more
    # generous windows.
    GAME_RECENT_WINDOW_DAYS = {
        "cs2":    14,   # CS2 trades continuously; require very-recent activity
        "league": 180,  # LoL plays in ~6-month chunks (Spring/MSI/Summer/Worlds)
    }
    GAME_DATA_WINDOW_DAYS = {
        "cs2":    60,
        "league": 240,  # capture last full LoL season for the wallet sample
    }

    # Rank wallets per-game (so a CS2 grinder and a LoL grinder can both appear)
    all_targets = []
    for game in GAMES:
        gdf_all = sub[sub["game"] == game]
        if not len(gdf_all):
            continue
        # Per-game latest_ts (NOT global) for both data window and recency cutoff
        g_latest = gdf_all["timestamp"].max()
        data_cutoff = g_latest - GAME_DATA_WINDOW_DAYS[game] * 24 * 3600
        recent_cutoff = g_latest - GAME_RECENT_WINDOW_DAYS[game] * 24 * 3600
        gdf = gdf_all[gdf_all["timestamp"] >= data_cutoff]
        print(f"  [{game}] sample window: {GAME_DATA_WINDOW_DAYS[game]}d -> {len(gdf):,} trades "
              f"ending {pd.Timestamp(g_latest, unit='s').date()}")

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

        # Lower trade-count floor for LoL since its volume is much smaller
        min_trades = 30 if game == "cs2" else 15
        tg = g[(g["trades"] >= min_trades) & (g["roi"] < -5) & (g["last_ts"] >= recent_cutoff)]
        tg = tg.sort_values("pnl").reset_index(drop=True)
        print(f"\n[{game}] active losing wallets (n>={min_trades}, ROI<-5%, last 14d): {len(tg)}")
        print(tg.head(10)[["proxyWallet", "trades", "wr", "pnl", "roi", "avg_pnl"]].to_string(index=False))
        # Wider top-K per game for PAPER detection — we collect signals on the
        # full pool. LIVE order placement is gated separately on a tighter subset.
        # CS2 gets 1000, LoL gets 400 for paper (signal collection).
        per_game_cap = 1000 if game == "cs2" else 400
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

    # LIVE subset = top losers by absolute PnL. Keeping LIVE tight (500) limits
    # daily $ exposure to the highest-conviction targets. PAPER (full 1000+)
    # captures the wider signal pool for ROI validation across more samples.
    live_subset = unique_wallets[:500]

    import os
    now_iso  = pd.Timestamp.utcnow().isoformat()
    # Global latest_ts across the dataset (used as "data_through" label)
    data_iso = pd.Timestamp(sub["timestamp"].max(), unit="s").isoformat()

    # ── Write PAPER targets (wider list, used for detection by the bot) ────
    paper_out = {
        "generated_at": now_iso,
        "data_through": data_iso,
        "games":          GAMES,
        "scope":          "paper_detection",
        "target_wallets": unique_wallets,
        "target_meta":    targets.to_dict(orient="records"),
    }
    paper_path = ES_DIR / "fade_targets_paper.json"
    tmp = paper_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(paper_out, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, paper_path)
    print(f"\nSaved {len(unique_wallets)} PAPER target wallets across {GAMES}: {paper_path}")

    # ── Write LIVE subset (used by bot to gate place_live_order) ───────────
    live_out = {
        "generated_at": now_iso,
        "data_through": data_iso,
        "games":          GAMES,
        "scope":          "live_subset",
        "target_wallets": live_subset,
        "target_meta":    targets.head(500).to_dict(orient="records"),
    }
    live_path = ES_DIR / "fade_targets.json"   # name kept for back-compat
    tmp = live_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(live_out, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, live_path)
    print(f"Saved {len(live_subset)} LIVE-subset target wallets: {live_path}")


if __name__ == "__main__":
    main()
