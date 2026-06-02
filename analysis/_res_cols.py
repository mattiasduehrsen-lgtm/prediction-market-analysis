import pandas as pd
from pathlib import Path
ES=Path("cowork_snapshot")/"esports"
r=pd.read_parquet(ES/"resolutions.parquet")
print("resolutions cols:", list(r.columns))
print(r.head(3).to_string())
print("\nmarkets cols sample with outcomes/tokens:")
m=pd.read_parquet(ES/"clob_esports_markets.parquet")
cs=m[m["slug"].fillna("").str.startswith("cs2-")]
row=cs.iloc[0]
print("tokens example:", row["tokens"])
print("question:", row["question"])
