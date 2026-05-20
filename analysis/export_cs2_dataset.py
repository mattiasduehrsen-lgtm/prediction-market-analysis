"""Package the 3-year CS2 trade history into a clean, shareable folder.

Output: cowork_snapshot/esports/exports/cs2_dataset_<date>/
  - trades.parquet         (all CS2 trades, one row per fill)
  - resolutions.parquet    (winning_outcome per market for PnL computation)
  - README.md              (column dictionary + example pandas snippet)
  - sample_trades.csv      (first 5000 rows for quick eyeballing)

Designed to be self-contained — a friend can drop the folder anywhere and
load it with pandas without needing access to the rest of this repo.
"""
from __future__ import annotations
import glob
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES   = ROOT / "cowork_snapshot" / "esports"
OUT_ROOT = ES / "exports"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

stamp = date.today().isoformat()
OUT = OUT_ROOT / f"cs2_dataset_{stamp}"
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)


def main() -> None:
    print("Loading shards...")
    shards = sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet")))
    print(f"  {len(shards)} shard files")
    df = pd.concat([pd.read_parquet(s) for s in shards], ignore_index=True)
    print(f"  {len(df):,} total trades across all games")

    # Filter to CS2. The slug naming convention is "cs2-..." for all
    # current matches; "csgo-..." was an older prefix the same data uses.
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    slug = df["slug"].fillna("").astype(str)
    cs2 = df[slug.str.startswith("cs2-") | slug.str.startswith("csgo-")].copy()
    cs2 = cs2.sort_values("timestamp").reset_index(drop=True)
    print(f"  {len(cs2):,} CS2 trades after filtering")

    # Add a human-readable datetime column on top of the epoch timestamp.
    cs2["datetime_utc"] = pd.to_datetime(cs2["timestamp"], unit="s", utc=True)

    # Keep only columns useful for analysis. Drop blockchain noise like
    # blockHash, gasUsed, etc. if present.
    keep = [
        "timestamp", "datetime_utc",
        "proxyWallet", "transactionHash",
        "conditionId", "slug",
        "side", "outcome", "outcomeIndex",
        "price", "size",
    ]
    keep = [c for c in keep if c in cs2.columns]
    cs2 = cs2[keep]
    print(f"  Columns kept: {keep}")

    trades_path = OUT / "trades.parquet"
    cs2.to_parquet(trades_path, index=False, compression="snappy")
    size_mb = trades_path.stat().st_size / 1024 / 1024
    print(f"  -> wrote {trades_path.name} ({size_mb:.1f} MB)")

    # Resolutions for the markets touched in this dataset
    res_path = ES / "resolutions.parquet"
    if res_path.exists():
        res = pd.read_parquet(res_path)
        cs2_cids = set(cs2["conditionId"].unique())
        res = res[res["condition_id"].isin(cs2_cids)].copy()
        out_res = OUT / "resolutions.parquet"
        res.to_parquet(out_res, index=False, compression="snappy")
        size_mb = out_res.stat().st_size / 1024 / 1024
        print(f"  -> wrote {out_res.name} ({size_mb:.1f} MB, "
              f"{len(res):,} markets, {res['resolved'].sum():,} resolved)")

    # Sample CSV for quick inspection
    sample_path = OUT / "sample_trades.csv"
    cs2.head(5000).to_csv(sample_path, index=False)
    print(f"  -> wrote {sample_path.name} (first 5000 rows)")

    # README
    earliest = cs2["datetime_utc"].min()
    latest   = cs2["datetime_utc"].max()
    wallets  = cs2["proxyWallet"].nunique()
    markets  = cs2["slug"].nunique()
    readme = OUT / "README.md"
    readme.write_text(encoding="utf-8", data=f"""# CS2 Polymarket Trade Dataset

Compiled {stamp}. Pulled from Polymarket's on-chain trade history via
the `data-api.polymarket.com/trades` endpoint, then merged with market
resolutions from the gamma-api.

## Summary
- **{len(cs2):,}** trades
- **{wallets:,}** unique wallets
- **{markets:,}** unique markets (one match = ~3-8 markets: match winner,
  per-map handicaps, total maps over/under, etc.)
- **{earliest:%Y-%m-%d}** to **{latest:%Y-%m-%d}**
  ({(latest - earliest).days} days)

## Files

| File | Rows | What it is |
|---|---|---|
| `trades.parquet`      | {len(cs2):,} | One row per filled trade |
| `resolutions.parquet` | per market   | `condition_id, winning_outcome, resolved, slug` |
| `sample_trades.csv`   | 5,000        | First 5k rows for spreadsheet eyeballing |

## Column dictionary — `trades.parquet`

| Column | Type | Notes |
|---|---|---|
| `timestamp`       | int   | Unix epoch seconds, UTC |
| `datetime_utc`    | dt    | Same value, human-readable |
| `proxyWallet`     | str   | The trader's Polymarket proxy address (lowercase 0x...). Stable across trades — this is the "who" |
| `transactionHash` | str   | On-chain tx hash, unique per fill |
| `conditionId`     | str   | The market's CTF conditionId (key for joining to resolutions) |
| `slug`            | str   | Human-readable market slug, e.g. `cs2-navi-spirit-2025-09-01-game1` |
| `side`            | str   | `BUY` or `SELL` |
| `outcome`         | str   | Which side they took, e.g. `Natus Vincere` or `Yes` |
| `outcomeIndex`    | int   | 0 or 1 (Polymarket markets are binary; the two `outcome` strings map to indices) |
| `price`           | float | Fill price in $ (0.00 – 1.00, where 1.00 = certain win) |
| `size`            | float | Number of shares filled (each share pays $1 if outcome wins) |

A trader's $-spend on a fill = `price * size`. If their outcome wins,
they receive `size` dollars (so PnL = `size - price*size` = `size*(1-price)`).

## Computing wallet PnL

```python
import pandas as pd
tr = pd.read_parquet("trades.parquet")
res = pd.read_parquet("resolutions.parquet").rename(columns=dict(condition_id="conditionId"))
df  = tr.merge(res[["conditionId", "winning_outcome", "resolved"]], on="conditionId")
df  = df[df["resolved"] & df["winning_outcome"].notna()]

# Whether each trade ended a winner:
import numpy as np
sell = df["side"].eq("SELL")
won  = np.where(sell, df["outcome"] != df["winning_outcome"],
                      df["outcome"] == df["winning_outcome"])
df["won"] = won

# Per-wallet rough PnL (assume $5 effective bet per trade):
df["bet"]    = 5.0
df["shares"] = df["bet"] / df["price"].clip(0.05, 0.95)
df["pnl"]    = np.where(df["won"], df["shares"] - df["bet"], -df["bet"])
print(df.groupby("proxyWallet")["pnl"].sum().sort_values().head(20))
```

## Provenance & limitations

- **Source.** Polymarket public APIs (`data-api`, `gamma-api`). No
  permissioned data. Trades that never settled on-chain aren't present.
- **Coverage.** CS2-tagged markets only — match winners, map winners,
  series handicaps, total-map over/unders. Excludes non-esports markets
  that happen to mention CS2 players.
- **Resolution lag.** Some recent markets ({(latest - pd.Timedelta(days=7)):%Y-%m-%d} to
  {latest:%Y-%m-%d}) may show `resolved=False` even if the game has
  finished — the Polymarket oracle takes a few hours to days to finalize.
  When joining for backtests, filter `resolved=True`.
- **Wallet sizes are not stake.** A wallet's `size` on a trade is the
  number of shares filled, not dollars. They're related but not identical:
  $5 buy at $0.40 = 12.5 shares. The dataset has no `usd_filled` column.
""")
    print(f"  -> wrote {readme.name}")

    print()
    print(f"DONE. Folder: {OUT}")
    print(f"Total folder size: "
          f"{sum(f.stat().st_size for f in OUT.iterdir())/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
