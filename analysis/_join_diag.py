import re
from pathlib import Path
import pandas as pd
GD = Path("cowork_snapshot")/"gamedata"
def norm(s):
    if not isinstance(s,str): return ""
    s=s.lower(); s=re.sub(r"[^a-z0-9 ]","",s)
    for j in [" esports"," gaming"," team "," e-sports"," academy"]: s=s.replace(j," ")
    return re.sub(r"\s+"," ",s).strip()
elo=pd.read_parquet(GD/"pandascore"/"cs2_elo_history.parquet")
mk=pd.read_parquet(GD/"polymarket_cs2_markets.parquet")
mk=mk[(~mk["is_single_map"])&mk["resolved"].fillna(False)&mk["game_start"].notna()]
# PandaScore team-name universe (normalized)
ps_names=set()
for c in ["teamA_name","teamB_name"]:
    ps_names|=set(elo[c].dropna().map(norm))
print("PandaScore distinct normalized team names:",len(ps_names))
# How many Polymarket markets have BOTH teams present in PandaScore by name?
both=0; one=0; none=0; samples=[]
for r in mk.itertuples(index=False):
    a,b=norm(r.teamA),norm(r.teamB)
    ia,ib=a in ps_names,b in ps_names
    if ia and ib: both+=1
    elif ia or ib: one+=1
    else:
        none+=1
        if len(samples)<12: samples.append((r.teamA,r.teamB))
print(f"series markets: {len(mk)}")
print(f"  both teams in PandaScore: {both}")
print(f"  one team: {one}")
print(f"  neither: {none}")
print("\nsample markets where NEITHER team matched (name mismatch pattern):")
for a,b in samples: print(f"   '{a}' vs '{b}'  -> norm '{norm(a)}' / '{norm(b)}'")
# Also: date coverage — elo history date range
elo["d"]=pd.to_datetime(elo["begin_at"],utc=True)
print(f"\nelo history date range: {elo['d'].min()} .. {elo['d'].max()}")
print(f"polymarket series date range: {pd.to_datetime(mk['game_start'],utc=True).min()} .. {pd.to_datetime(mk['game_start'],utc=True).max()}")
