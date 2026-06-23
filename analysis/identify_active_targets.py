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
    # Game classification. NOT just slug.split('-')[0] — that labels LoL markets
    # 'lol'/'arch' (e.g. 'lol-t1-geng', 'arch-lol-...') and would EXCLUDE those
    # bettors from the 'league' targets. Map all LoL slug variants -> 'league'
    # (Valorant 'vct'/'valorant' excluded — its slugs carry 'league' too).
    def _game_of(slug: str) -> str:
        s = (slug or "").lower()
        if "vct" in s or "valorant" in s: return "valorant"
        if s.startswith(("cs2-", "csgo-")) or "-cs2" in s or "-csgo" in s: return "cs2"
        if (s.startswith(("lol-", "arch-lol-", "league-")) or "league-of-legends" in s
                or "-lol-" in s): return "league"
        return s.split("-")[0]
    df["game"] = df["mkt_slug"].fillna("").map(_game_of)

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
        g["trades_per_day"] = (g["trades"] / GAME_DATA_WINDOW_DAYS[game]).round(2)

        # ── RECENT-WINDOW persistence (v1.39) ────────────────────────────────
        # A wallet that was a loser over the full window might have turned
        # around recently. Compute ROI over just the recent window and require
        # it to STILL be losing, so we don't fade reformed/improving wallets.
        rdf = gdf[gdf["timestamp"] >= recent_cutoff]
        rg = rdf.groupby("proxyWallet").agg(
            r_trades=("pnl", "size"),
            r_pnl=("pnl", "sum"),
        ).reset_index()
        rg["recent_roi"] = (rg["r_pnl"] / (rg["r_trades"] * BET) * 100).round(2)
        g = g.merge(rg, on="proxyWallet", how="left")

        # ── BOT / MARKET-MAKER EXCLUSION (v1.39) ─────────────────────────────
        # The single biggest leak in the live book (diagnostic 2026-05-29):
        # wallet 0x47138dc1 traded 95,730 times (-11% ROI, -$53k). That's a
        # market maker, not a recreational loser. MMs capture the spread and
        # look mildly negative on naive directional PnL, but fading them just
        # pays the vig. Exclude anything trading faster than a human plausibly
        # could. Heavy degens do <30/day; MMs do hundreds-to-thousands/day.
        MAX_TRADES_PER_DAY = 30.0
        bots = g[g["trades_per_day"] > MAX_TRADES_PER_DAY]
        if len(bots):
            print(f"  [{game}] excluding {len(bots)} bot/MM wallets "
                  f"(>{MAX_TRADES_PER_DAY}/day). Top by volume:")
            print(bots.sort_values("trades", ascending=False)
                  .head(5)[["proxyWallet","trades","trades_per_day","wr","roi"]]
                  .to_string(index=False))
        g = g[g["trades_per_day"] <= MAX_TRADES_PER_DAY]

        min_trades = 30 if game == "cs2" else 15

        # ── PAPER detection list (wide) — ROI<-5, still-losing-recently ──────
        # Kept generous for signal collection. recent_roi may be NaN if the
        # wallet had no trades in the recent window; treat NaN as "not recent".
        paper_tg = g[(g["trades"] >= min_trades)
                     & (g["roi"] < -5)
                     & (g["last_ts"] >= recent_cutoff)
                     & (g["recent_roi"].fillna(0) < 0)]
        paper_tg = paper_tg.sort_values("roi").reset_index(drop=True)
        print(f"\n[{game}] PAPER losing wallets "
              f"(n>={min_trades}, ROI<-5%, recent_roi<0, <={MAX_TRADES_PER_DAY}/day): {len(paper_tg)}")
        print(paper_tg.head(10)[["proxyWallet","trades","trades_per_day","wr","roi","recent_roi"]]
              .to_string(index=False))
        per_game_cap = 1000 if game == "cs2" else 400
        all_targets.append(paper_tg.head(per_game_cap))

    if not all_targets:
        print("\nNo targets found — aborting")
        return
    # Rank by ROI ascending (worst EDGE first) — NOT absolute pnl. The old
    # pnl-ranking surfaced the highest-VOLUME wallets (bots/MMs), not the
    # wallets with the worst per-trade edge. (v1.39 fix.)
    targets = pd.concat(all_targets, ignore_index=True).sort_values("roi").reset_index(drop=True)

    # Deduplicate — a wallet active in multiple games appears once
    seen = set()
    unique_wallets = []
    for _, r in targets.iterrows():
        w = r["proxyWallet"]
        if w in seen:
            continue
        seen.add(w)
        unique_wallets.append(w)

    # ── LIVE subset (v1.39) — HIGH-CONVICTION persistent losers only ─────────
    # Previously this was just paper[:800] sorted by absolute pnl, which put a
    # 95k-trade market maker at #1. New rule: a wallet must be a STRONG loser
    # (full-window ROI < -15%) AND still losing recently (recent_roi < -5%),
    # ranked by worst ROI, capped tight. Fewer, better targets = more edge per
    # fade and less exposure to mislabeled non-losers.
    LIVE_ROI_THRESHOLD = -15.0
    LIVE_RECENT_ROI_THRESHOLD = -5.0
    LIVE_WALLET_CAP = 300
    live_df = targets[(targets["roi"] < LIVE_ROI_THRESHOLD)
                      & (targets["recent_roi"].fillna(0) < LIVE_RECENT_ROI_THRESHOLD)]
    live_df = live_df.sort_values("roi").drop_duplicates("proxyWallet")
    # RESERVE CS2 SLOTS. CS2 is the only LIVE-tradeable game; LoL is observe-only.
    # The GRID LoL market explosion (54k+ markets) floods this list with league
    # losers that, ranked by worst ROI, crowded CS2 out ENTIRELY (CS2 -> 0 live
    # targets on 2026-06-23, silently killing live trading). So take ALL CS2
    # qualifiers first, then fill the remaining cap with league/other. CS2
    # qualifiers are few (~tens), so LoL still gets the bulk for observe-only.
    cs2_live = live_df[live_df["game"] == "cs2"]
    other_live = live_df[live_df["game"] != "cs2"]
    ordered = pd.concat([cs2_live, other_live]).drop_duplicates("proxyWallet")
    live_subset = list(ordered["proxyWallet"].head(LIVE_WALLET_CAP))
    n_cs2 = int((ordered.head(LIVE_WALLET_CAP)["game"] == "cs2").sum())
    print(f"\nLIVE subset: {len(live_subset)} wallets (cs2={n_cs2} reserved-first, "
          f"rest league/other; ROI<{LIVE_ROI_THRESHOLD}%, recent_roi<{LIVE_RECENT_ROI_THRESHOLD}%, cap {LIVE_WALLET_CAP})")

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
        "target_meta":    live_df.head(LIVE_WALLET_CAP).to_dict(orient="records"),
    }
    live_path = ES_DIR / "fade_targets.json"   # name kept for back-compat
    tmp = live_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(live_out, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, live_path)
    print(f"Saved {len(live_subset)} LIVE-subset target wallets: {live_path}")


if __name__ == "__main__":
    main()
