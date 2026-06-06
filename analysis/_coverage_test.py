import sys, requests
from pathlib import Path
from collections import Counter
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cs2_model import CS2Model
m = CS2Model()
# recent bo3 team names from the live games feed (the teams we'd actually face)
g = requests.get("https://api.bo3.gg/api/v1/games",params={"sort":"-begin_at","page[limit]":200},
                 headers={"User-Agent":"Mozilla/5.0"},timeout=15).json()["results"]
teams=set()
for x in g:
    for k in ("winner_clan_name","loser_clan_name"):
        if x.get(k): teams.add(x[k].strip())
matched=[t for t in teams if m.match_team(t)]
unmatched=[t for t in teams if not m.match_team(t)]
print(f"recent distinct teams: {len(teams)}")
print(f"  matched to Elo: {len(matched)} ({len(matched)/max(len(teams),1)*100:.0f}%)")
print(f"  UNMATCHED ({len(unmatched)}): {sorted(unmatched)[:40]}")
