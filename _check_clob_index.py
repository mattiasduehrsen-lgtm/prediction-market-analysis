"""Quick look at what's in clob_markets.parquet — does it have NHL/sports?"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
df = pd.read_parquet(ROOT / "cowork_snapshot" / "esports" / "clob_markets.parquet")
print(f"Total markets in clob_markets.parquet: {len(df):,}")
print(f"Columns: {list(df.columns)[:15]}")
print()

slugs = df["slug"].fillna("").astype(str)
prefixes = slugs.str.extract(r"^([a-z0-9]+)-")[0].value_counts()
print("Top 25 slug prefixes (proxy for sport/category):")
for prefix, count in prefixes.head(25).items():
    print(f"  {prefix:<20} {count:>6}")

print()
print("Sample NHL-looking slugs:")
nhl = df[slugs.str.contains("nhl|stanley|hurricanes|avalanche|knights|panthers", regex=True, case=False)].head(10)
for s in nhl["slug"].head(10).tolist():
    print(f"  {s}")
