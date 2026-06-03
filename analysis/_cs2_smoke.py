import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cs2_model import CS2Model
import cs2_model_bot as bot
m = CS2Model()
print(f"teams with elo: {len(m.elo_by_id)}, name keys: {len(m.name_to_id)}")
# predict known matchups
for a,b in [("NRG","TYLOO"),("FaZe","Vitality"),("MOUZ","G2"),("Spirit","Falcons"),("3DMAX","Magic")]:
    p = m.predict(a,b)
    print(f"  {a} vs {b}: {p}")
# test market load + window
cache={}
df = bot.load_markets(cache)
import pandas as pd
from datetime import datetime, timezone, timedelta
now=datetime.now(timezone.utc)
up = df[(df["game_start"].notna()) & (~df["closed"].fillna(False)) & (df["game_start"]>now)]
print(f"total cs2 markets: {len(df)}, upcoming (future, open): {len(up)}")
soon = up[up["game_start"]<=now+timedelta(hours=6)].sort_values("game_start")
print("next 6h upcoming sample:")
for r in soon.head(8).itertuples(index=False):
    t = bot.parse_teams(r.question)
    print(f"   {r.game_start}  {t}")
