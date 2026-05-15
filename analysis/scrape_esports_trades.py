"""
Scrape complete trade history for every esports market from Polymarket
data-api. Resumable: writes per-batch parquet shards and a progress manifest.

Resume by re-running — anything already shard'd is skipped.

Output:
  cowork_snapshot/esports/scrape/shards/*.parquet  — one shard per N markets
  cowork_snapshot/esports/scrape/manifest.json     — resume state
"""
import argparse
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR  = ROOT / "cowork_snapshot" / "esports" / "scrape"
SHARDS   = OUT_DIR / "shards"
SHARDS.mkdir(parents=True, exist_ok=True)
MANIFEST = OUT_DIR / "manifest.json"

API = "https://data-api.polymarket.com/trades"
PAGE_SIZE = 500
SLEEP_BETWEEN_CALLS = 0.15   # ~6-7 req/sec — conservative to avoid rate limits
MARKETS_PER_SHARD = 100


def load_manifest():
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed_conditions": [], "shard_index": 0, "total_trades": 0}


def save_manifest(m):
    MANIFEST.write_text(json.dumps(m), encoding="utf-8")


def fetch_market_trades(condition_id):
    """Paginate trades for one market. Returns list of dicts."""
    out = []
    offset = 0
    while True:
        try:
            r = requests.get(API, params={
                "market": condition_id,
                "limit":  PAGE_SIZE,
                "offset": offset,
            }, timeout=20)
        except Exception as e:
            print(f"  network error on {condition_id[:14]} offset {offset}: {e}")
            time.sleep(2)
            continue
        if r.status_code == 429:
            print("  rate-limited, sleeping 10s")
            time.sleep(10)
            continue
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} on {condition_id[:14]} offset {offset}")
            break
        page = r.json()
        if not page:
            break
        out.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(SLEEP_BETWEEN_CALLS)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-markets", type=int, default=0,
                    help="Stop after this many markets (0 = all)")
    args = ap.parse_args()

    es = pd.read_parquet(ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet")
    es = es[es["condition_id"].astype(str).str.startswith("0x")].copy()
    print(f"Markets to scrape: {len(es)}")

    manifest = load_manifest()
    done = set(manifest["completed_conditions"])
    print(f"Already done: {len(done)}")

    shard_buf = []
    shard_idx = manifest["shard_index"]
    total_new_trades = 0
    t_start = time.time()
    n_processed = 0

    for i, row in es.iterrows():
        cond = row["condition_id"]
        if cond in done:
            continue
        n_processed += 1
        if args.limit_markets and n_processed > args.limit_markets:
            break

        trades = fetch_market_trades(cond)
        for t in trades:
            t["_scrape_slug"] = row["slug"]
            t["_scrape_es_keyword"] = row.get("es_keyword", "")
            t["_scrape_neg_risk"] = bool(row.get("neg_risk", False))
        shard_buf.extend(trades)
        total_new_trades += len(trades)
        done.add(cond)

        # Per-market progress line (terse)
        if n_processed % 20 == 0:
            elapsed = time.time() - t_start
            rate = n_processed / elapsed if elapsed > 0 else 0
            eta_min = (len(es) - len(done)) / rate / 60 if rate > 0 else -1
            print(f"  {n_processed:>5} markets, {total_new_trades:>7,} new trades, "
                  f"{rate:.1f} mkt/s, ETA {eta_min:.0f}min")

        # Flush shard
        if len(shard_buf) >= MARKETS_PER_SHARD * 50:   # ~5000 rows per shard
            df = pd.DataFrame(shard_buf)
            shard_path = SHARDS / f"shard_{shard_idx:05d}.parquet"
            df.to_parquet(shard_path, index=False)
            print(f"  [flush] shard {shard_idx} ({len(df):,} rows) -> {shard_path.name}")
            shard_buf = []
            shard_idx += 1
            manifest["shard_index"] = shard_idx
            manifest["completed_conditions"] = list(done)
            manifest["total_trades"] = manifest.get("total_trades", 0) + len(df)
            save_manifest(manifest)

    # Final flush
    if shard_buf:
        df = pd.DataFrame(shard_buf)
        shard_path = SHARDS / f"shard_{shard_idx:05d}.parquet"
        df.to_parquet(shard_path, index=False)
        print(f"  [final flush] shard {shard_idx} ({len(df):,} rows)")
        shard_idx += 1
        manifest["shard_index"] = shard_idx
        manifest["total_trades"] = manifest.get("total_trades", 0) + len(df)

    manifest["completed_conditions"] = list(done)
    save_manifest(manifest)

    print(f"\nDone. Markets processed: {n_processed}, total trades fetched: {manifest['total_trades']:,}")
    print(f"Shards: {SHARDS}")


if __name__ == "__main__":
    main()
