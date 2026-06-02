"""For each Polymarket CS2 series market, find the last traded price of each
outcome BEFORE game_start = the market's pre-match implied probability.

Reads the trade shards (cowork_snapshot/esports/scrape/shards/*.parquet),
keeps only our target condition_ids, and records the latest pre-start price
per (condition_id, outcome).

Output: cowork_snapshot/gamedata/prematch_prices.parquet
"""
from __future__ import annotations
import glob
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
GD = ROOT / "cowork_snapshot" / "gamedata"

def main():
    mk = pd.read_parquet(GD / "polymarket_cs2_markets.parquet")
    mk = mk[(~mk["is_single_map"]) & mk["game_start"].notna()].copy()
    start_by_cid = dict(zip(mk["condition_id"], mk["game_start"].astype("int64") // 10**9))
    targets = set(start_by_cid)
    print(f"target series markets: {len(targets)}")

    shards = sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet")))
    print(f"scanning {len(shards)} trade shards...")
    # best[(cid, outcome)] = (ts, price)
    best: dict[tuple, tuple] = {}
    for i, sh in enumerate(shards):
        try:
            d = pd.read_parquet(sh, columns=["conditionId", "outcome", "price", "timestamp"])
        except Exception:
            continue
        d = d[d["conditionId"].isin(targets)]
        if not len(d):
            continue
        d["timestamp"] = pd.to_numeric(d["timestamp"], errors="coerce")
        d["price"] = pd.to_numeric(d["price"], errors="coerce")
        d = d.dropna(subset=["timestamp", "price"])
        for r in d.itertuples(index=False):
            gs = start_by_cid.get(r.conditionId)
            if gs is None or r.timestamp >= gs:
                continue  # only pre-match trades
            key = (r.conditionId, r.outcome)
            prev = best.get(key)
            if prev is None or r.timestamp > prev[0]:
                best[key] = (r.timestamp, float(r.price))
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(shards)} shards, {len(best)} (cid,outcome) prices so far")

    rows = [{"condition_id": cid, "outcome": oc, "ts": ts, "price": px,
             "secs_before_start": start_by_cid[cid] - ts}
            for (cid, oc), (ts, px) in best.items()]
    out = pd.DataFrame(rows)
    out.to_parquet(GD / "prematch_prices.parquet")
    print(f"\npre-match prices: {len(out)} (cid,outcome) rows for "
          f"{out['condition_id'].nunique() if len(out) else 0} markets")
    if len(out):
        print(f"  median secs before start: {out['secs_before_start'].median():.0f}")

if __name__ == "__main__":
    main()
