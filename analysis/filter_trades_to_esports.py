"""
Stream every parquet from a bulk_blockchain_trades_partN archive, filter to
esports token_ids only, and write the result to a parquet output.

Doesn't unzip the full archive — uses zipfile to stream each member parquet,
filter rows, append to the output. Memory bounded.

Usage:
  python filter_trades_to_esports.py --zip C:\\path\\to\\partN.zip --out cowork_snapshot/esports/esports_trades_partN.parquet
"""
import argparse
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR  = ROOT / "cowork_snapshot" / "esports"

# Load token whitelist from clob index
idx = json.loads((OUT_DIR / "clob_token_to_market.json").read_text(encoding="utf-8"))
TOK2COND = idx["token_to_condition"]
TOK2SLUG = idx["token_to_slug"]
TOKEN_SET = set(TOK2COND.keys())
print(f"Esports token whitelist: {len(TOKEN_SET)} tokens")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, help="Path to bulk_blockchain_trades_partN.zip")
    ap.add_argument("--out", required=True, help="Output parquet path")
    args = ap.parse_args()
    ZIP_PATH = Path(args.zip)
    OUT_TRADES = Path(args.out)
    OUT_TRADES.parent.mkdir(parents=True, exist_ok=True)
    if not ZIP_PATH.exists():
        raise SystemExit(f"zip not found: {ZIP_PATH}")
    chunks = []
    total_in = 0
    total_kept = 0
    files_done = 0

    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = [n for n in zf.namelist() if n.endswith(".parquet")]
        print(f"Parquet files in archive: {len(names)}")
        for name in sorted(names):
            with zf.open(name) as fh:
                buf = BytesIO(fh.read())
                table = pq.read_table(buf, columns=["timestamp","datetime_utc","token_id","side","price","size","fee","exchange","maker","taker"])
                df = table.to_pandas()
            n_in = len(df)
            total_in += n_in
            df["token_id"] = df["token_id"].astype(str)
            mask = df["token_id"].isin(TOKEN_SET)
            kept = df[mask].copy()
            if len(kept):
                kept["condition_id"] = kept["token_id"].map(TOK2COND)
                kept["slug"]         = kept["token_id"].map(TOK2SLUG)
                chunks.append(kept)
                total_kept += len(kept)
            files_done += 1
            if files_done % 5 == 0 or files_done == len(names):
                print(f"  {files_done}/{len(names)}  in={total_in:>10,}  kept={total_kept:>9,}  ratio={total_kept/total_in*100:.2f}%")

    if not chunks:
        print("No esports trades found.")
        return

    out = pd.concat(chunks, ignore_index=True)
    print(f"\nTotal kept rows: {len(out):,}")
    out.to_parquet(OUT_TRADES, index=False)
    print(f"Saved: {OUT_TRADES}")

    # Quick audit
    print("\nDate range:")
    print(f"  earliest: {out['datetime_utc'].min()}")
    print(f"  latest:   {out['datetime_utc'].max()}")
    print(f"\nUnique conditions traded: {out['condition_id'].nunique():,}")
    print(f"Unique slugs traded:      {out['slug'].nunique():,}")
    print(f"By exchange:")
    print(out["exchange"].value_counts().to_string())
    print(f"\nTop 10 most-traded esports markets:")
    print(out.groupby("slug").size().sort_values(ascending=False).head(10).to_string())


if __name__ == "__main__":
    main()
