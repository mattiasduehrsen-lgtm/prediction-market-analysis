"""Build sports_fade_targets.json from per-sport losing-wallets parquets.

Consolidates qualifying losing wallets across NHL, NBA, MLB, Tennis, Soccer
into one JSON file the sports paper bot can consume. Also builds
clob_sports_markets.parquet — the filtered market index used for slug→outcome
lookups during signal processing.

Re-runnable. Atomic-replaces target file so the live bot's mtime-watch
auto-reloads cleanly.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COWORK = ROOT / "cowork_snapshot"
SPORTS_DIR = COWORK / "sports"
SPORTS_DIR.mkdir(parents=True, exist_ok=True)

GOOD_SPORTS = ["nhl", "nba", "mlb", "tennis", "soccer"]
SPORT_PREFIXES = {
    "nhl":    ["nhl-"],
    "nba":    ["nba-"],
    "mlb":    ["mlb-"],
    "tennis": ["atp-", "wta-"],
    "soccer": ["epl-", "laliga-", "champions-", "uefa-", "fifa-"],
}


def build_targets() -> dict:
    """Merge per-sport losing-wallets parquets into a unified list."""
    all_wallets = {}  # wallet -> {trades, pnl, sports_set}
    for sport in GOOD_SPORTS:
        f = COWORK / f"{sport}_recon" / "losing_wallets.parquet"
        if not f.exists():
            print(f"  [skip] {sport}: losing_wallets.parquet missing")
            continue
        df = pd.read_parquet(f)
        for w, row in df.iterrows():
            wl = w.lower()
            if wl not in all_wallets:
                all_wallets[wl] = {"trades": 0, "pnl": 0.0, "sports": set()}
            all_wallets[wl]["trades"] += int(row["trades"])
            all_wallets[wl]["pnl"] += float(row["pnl"])
            all_wallets[wl]["sports"].add(sport)
        print(f"  [load] {sport}: {len(df)} wallets")

    # Sort by total PnL (biggest losers first)
    sorted_w = sorted(all_wallets.items(), key=lambda x: x[1]["pnl"])
    wallet_list = [w for w, _ in sorted_w]

    print(f"\nTotal unique sports losers: {len(wallet_list):,}")
    print(f"Top 5 (biggest losers across sports):")
    for w, info in sorted_w[:5]:
        print(f"  {w}  pnl=${info['pnl']:>10,.0f}  trades={info['trades']:>5}  "
              f"sports={sorted(info['sports'])}")

    meta = [
        {"wallet": w, "pnl_usd": round(info["pnl"], 2),
         "trades": info["trades"], "sports": sorted(info["sports"])}
        for w, info in sorted_w
    ]
    return {
        "generated_at":    dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope":           "sports_paper",
        "games":           GOOD_SPORTS,
        "target_wallets":  wallet_list,
        "target_meta":     meta,
    }


def filter_clob_markets() -> int:
    """Filter clob_markets.parquet to sports markets only and save."""
    src = COWORK / "esports" / "clob_markets.parquet"
    if not src.exists():
        print(f"  [WARN] {src} missing — sports bot won't have market metadata")
        return 0
    df = pd.read_parquet(src)
    slugs = df["slug"].fillna("").astype(str).str.lower()
    mask = pd.Series(False, index=df.index)
    for prefixes in SPORT_PREFIXES.values():
        for p in prefixes:
            mask |= slugs.str.startswith(p)
    out = df[mask].copy()
    out_path = SPORTS_DIR / "clob_sports_markets.parquet"
    out.to_parquet(out_path, index=False)
    print(f"  Filtered {len(df):,} -> {len(out):,} sports markets at {out_path}")
    return len(out)


def main():
    print("=" * 70)
    print(" BUILD SPORTS FADE TARGETS")
    print("=" * 70)
    print()
    print("[1/3] Loading per-sport losing wallets...")
    targets = build_targets()

    print(f"\n[2/3] Filtering clob_markets.parquet for sports...")
    filter_clob_markets()

    print(f"\n[3/3] Writing fade_targets.json atomically...")
    out_path = SPORTS_DIR / "fade_targets.json"
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(targets, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, out_path)
    print(f"  Saved {len(targets['target_wallets']):,} wallets -> {out_path}")
    print(f"\nDONE.")


if __name__ == "__main__":
    main()
