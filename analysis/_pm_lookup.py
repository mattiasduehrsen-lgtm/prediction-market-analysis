import pandas as pd, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
df=pd.read_parquet(ROOT/"cowork_snapshot"/"esports"/"clob_esports_markets.parquet",
                   columns=["slug","question","game_start","closed"])
now=datetime.now(timezone.utc)
df["gs"]=pd.to_datetime(df["game_start"],errors="coerce",utc=True)
# any market mentioning spirit or 9z
hit=df[df["question"].fillna("").str.contains("9z",case=False) | df["question"].fillna("").str.contains("spirit",case=False)]
hit=hit[hit["slug"].fillna("").str.startswith("cs2-")]
print(f"cs2 markets mentioning spirit/9z: {len(hit)}")
recent=hit[hit["gs"]>now-timedelta(hours=12)].sort_values("gs")
print("recent (last 12h):")
for r in recent.tail(12).itertuples():
    age=(now-r.gs).total_seconds()/3600
    print(f"  gs={r.gs.strftime('%m-%d %H:%M')} ({age:+.1f}h) closed={r.closed} | {str(r.question)[:55]}")
print(f"\nnow UTC: {now.strftime('%m-%d %H:%M')}")
print("parquet newest game_start:", df['gs'].max())
