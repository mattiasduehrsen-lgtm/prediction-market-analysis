"""
Extract resolved outcomes from the CLOB index (which now includes `winner`
per token). Much faster than the original — no API calls needed since the
data was already pulled during index build.

Output: cowork_snapshot/esports/resolutions.parquet
"""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES_DIR = ROOT / "cowork_snapshot" / "esports"


def main():
    es = pd.read_parquet(ES_DIR / "clob_esports_markets.parquet")
    rows = []
    n_resolved = 0
    for _, m in es.iterrows():
        toks = m["tokens"]
        # numpy arrays from parquet — iterate directly
        winning_outcome = None
        winning_token = None
        try:
            for t in toks:
                if t.get("winner"):
                    winning_outcome = t.get("outcome")
                    winning_token   = t.get("token_id")
                    break
        except TypeError:
            pass
        if winning_outcome:
            n_resolved += 1
        rows.append({
            "condition_id":  m["condition_id"],
            "slug":          m["slug"],
            "resolved":      bool(m.get("closed")) and (winning_outcome is not None),
            "closed":        bool(m.get("closed")),
            "winning_outcome": winning_outcome,
            "winning_token":   winning_token,
        })

    df = pd.DataFrame(rows)
    df.to_parquet(ES_DIR / "resolutions.parquet", index=False)
    print(f"Total markets: {len(df):,}")
    print(f"Resolved with winner: {n_resolved:,}  ({n_resolved/len(df)*100:.1f}%)")
    print(f"\nWinner distribution:")
    print(df["winning_outcome"].value_counts(dropna=False).head(10).to_string())


if __name__ == "__main__":
    main()
