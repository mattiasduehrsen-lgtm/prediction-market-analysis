"""Inspect the tokens field structure on clob_markets.parquet."""
import pandas as pd
from pathlib import Path
ROOT = Path(__file__).resolve().parent
df = pd.read_parquet(ROOT / "cowork_snapshot" / "esports" / "clob_markets.parquet")
slugs = df["slug"].fillna("").astype(str).str.lower()
nhl = df[slugs.str.startswith("nhl-")].head(5)
for _, row in nhl.iterrows():
    print(f"slug: {row['slug']}")
    print(f"  closed: {row.get('closed')}")
    print(f"  active: {row.get('active')}")
    print(f"  end_date: {row.get('end_date')}")
    t = row.get("tokens")
    print(f"  tokens type: {type(t).__name__}")
    if isinstance(t, str):
        print(f"  tokens (str, first 200): {t[:200]}")
    else:
        print(f"  tokens (raw): {t}")
    print()
