"""
For every esports condition_id, fetch the resolved outcome (which side won).

gamma-api /markets accepts condition_ids batch queries. We look up the
`outcomePrices` field — when a market is resolved, this is ['1','0'] or
['0','1'] depending on which outcome won. We map that to "Yes" or "No".

Output: cowork_snapshot/esports/resolutions.parquet
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "cowork_snapshot" / "esports"
OUT_FILE = OUT_DIR / "resolutions.parquet"


def main():
    es = pd.read_parquet(OUT_DIR / "clob_esports_markets.parquet")
    conds = es["condition_id"].astype(str).tolist()
    print(f"Resolving {len(conds)} markets...")

    rows = []
    t0 = time.time()
    BATCH = 100
    for i in range(0, len(conds), BATCH):
        batch = conds[i:i+BATCH]
        params = [("condition_ids", c) for c in batch]
        try:
            r = requests.get(
                "https://gamma-api.polymarket.com/markets",
                params=params, timeout=20,
            )
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} batch {i}")
                time.sleep(2)
                continue
            for m in r.json():
                cid = m.get("conditionId") or ""
                try:
                    op = json.loads(m.get("outcomePrices") or "[]")
                    outcomes = json.loads(m.get("outcomes") or "[]")
                except Exception:
                    op, outcomes = [], []
                resolved = bool(m.get("closed") and not m.get("archived"))
                winner = None
                winning_price = None
                if resolved and len(op) >= 2 and len(outcomes) >= 2:
                    try:
                        prices = [float(x) for x in op]
                        # resolved markets: one side is 1.0, other 0.0 (or near)
                        if max(prices) > 0.95 and min(prices) < 0.05:
                            winner_idx = prices.index(max(prices))
                            winner = outcomes[winner_idx]
                            winning_price = prices[winner_idx]
                    except Exception:
                        pass
                rows.append({
                    "condition_id":  cid,
                    "slug":          m.get("slug") or "",
                    "resolved":      resolved,
                    "closed":        bool(m.get("closed")),
                    "archived":      bool(m.get("archived")),
                    "winning_outcome": winner,
                    "winning_price":   winning_price,
                    "outcome_prices":  op,
                    "outcomes":        outcomes,
                    "end_date":      m.get("endDate") or "",
                })
        except Exception as e:
            print(f"  error batch {i}: {e}")
            time.sleep(2)
            continue
        if (i // BATCH) % 5 == 0:
            print(f"  {i+BATCH}/{len(conds)}  resolved-so-far={sum(1 for r in rows if r['winning_outcome']):,}  elapsed={time.time()-t0:.0f}s")

    df = pd.DataFrame(rows)
    df.to_parquet(OUT_FILE, index=False)
    print(f"\nSaved: {OUT_FILE}")
    print(f"Total markets: {len(df):,}")
    print(f"Resolved with clear winner: {df['winning_outcome'].notna().sum():,}")
    print(f"Resolution rate: {df['winning_outcome'].notna().sum()/len(df)*100:.1f}%")
    print(f"\nWinner distribution:")
    print(df['winning_outcome'].value_counts(dropna=False).head(8).to_string())


if __name__ == "__main__":
    main()
