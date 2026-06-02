import pandas as pd
from pathlib import Path
p=Path("cowork_snapshot")/"esports"/"clob_esports_markets.parquet"
df=pd.read_parquet(p)
cs=df[df["slug"].fillna("").str.startswith("cs2-")]
print("total cs2 markets:",len(cs))
print("with game_start:",cs["game_start"].notna().sum())
print()
for _,r in cs.head(6).iterrows():
    print("slug:",r["slug"])
    print("  question:",r.get("question"))
    print("  game_start:",r.get("game_start"),"| closed:",r.get("closed"))
    print()
