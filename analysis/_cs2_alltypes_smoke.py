import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cs2_model_bot as bot
from cs2_model import CS2Model
import pandas as pd
from datetime import datetime, timezone, timedelta
m = CS2Model()
df = pd.read_parquet(Path("cowork_snapshot")/"esports"/"clob_esports_markets.parquet",
                     columns=["slug","question","game_start","closed"])
df = df[df["slug"].fillna("").str.startswith("cs2-")].copy()
df["game_start"]=pd.to_datetime(df["game_start"],errors="coerce",utc=True)
now=datetime.now(timezone.utc)
up=df[(df["game_start"]>now)&(~df["closed"].fillna(False))].sort_values("game_start").head(25)
from collections import Counter
types=Counter()
print(f"{'type':<9}{'teams extracted':<34}{'model?':<8}{'question'}")
for r in up.itertuples(index=False):
    mt=bot.classify_market(r.slug,r.question)
    types[mt]+=1
    teams=bot.extract_teams(r.question)
    pred = m.predict(*teams) if teams else None
    ok = "OK" if (pred and pred.get("ok")) else ((pred or {}).get("reason","none") if teams else "no-teams")
    ts = f"{teams[0]} / {teams[1]}" if teams else "-"
    print(f"{mt:<9}{ts[:33]:<34}{ok:<8}{str(r.question)[:46]}")
print("\ntype counts in next upcoming markets:", dict(types))
