"""Tiny helper: count laptop's data-api scrape rows in a given Unix-ts window."""
import sys, glob, pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
lo = int(sys.argv[1])
hi = int(sys.argv[2])
shards = sorted(glob.glob(str(ROOT / "cowork_snapshot/esports/scrape/shards/*.parquet")))
total = 0
for s in shards:
    df = pd.read_parquet(s, columns=["timestamp"])
    ts = pd.to_numeric(df["timestamp"], errors="coerce")
    total += ((ts >= lo) & (ts <= hi)).sum()
print(f"rows in window [{lo}, {hi}]: {total:,}")
