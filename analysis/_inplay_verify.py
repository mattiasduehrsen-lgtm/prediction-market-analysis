import sys, time, requests
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cs2_model import CS2Model, norm
S=requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json"})
games=(S.get("https://api.bo3.gg/api/v1/games",params={"sort":"-begin_at","page[limit]":200},timeout=15).json() or {}).get("results") or []
print(f"games fetched: {len(games)}")
live=[g for g in games if g.get("state") in ("current","started")]
print(f"games with LIVE state right now: {len(live)}")
by=defaultdict(list)
for g in games: by[g.get("match_id")].append(g)
# replicate bot detection: exactly 1 done + a live map
m=CS2Model()
post1=0
for mid,gs in by.items():
    done=[g for g in gs if g.get("winner_clan_name") and g.get("loser_clan_name")]
    livg=[g for g in gs if g.get("state") in ("current","started")]
    if len(done)==1 and livg:
        post1+=1
        g1=done[0]; tA=g1["winner_clan_name"].strip(); tB=g1["loser_clan_name"].strip()
        age=time.time()-__import__("pandas").Timestamp(livg[0]["begin_at"]).timestamp()
        mm=bool(m.match_team(tA)) and bool(m.match_team(tB))
        print(f"  POST-MAP-1: {tA} vs {tB} | live_map={livg[0].get('map_name')} age={age:.0f}s model_match={mm}")
print(f"\npost-map-1 live series detected NOW: {post1}")
if not live: print("=> bo3 shows NO live CS2 maps right now (genuinely quiet) — bot correctly idle")
