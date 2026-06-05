import json
from pathlib import Path
from collections import Counter
ROOT = Path(__file__).resolve().parents[1]
gp = ROOT/"cowork_snapshot"/"gamedata"/"bo3"/"games.jsonl"
games = [json.loads(l) for l in gp.read_text(encoding="utf-8").splitlines()]
print(f"games downloaded: {len(games)}")
# how many have a usable winner + map?
has_winner = sum(1 for g in games if g.get("winner_clan_name") and g.get("loser_clan_name"))
has_map = sum(1 for g in games if g.get("map_name"))
cs2 = sum(1 for g in games if g.get("game_version")==2)
print(f"  with winner+loser names: {has_winner} ({has_winner/len(games)*100:.0f}%)")
print(f"  with map_name: {has_map}")
print(f"  CS2 (game_version=2): {cs2}")
print("  map_name dist:", dict(Counter(g.get('map_name') for g in games).most_common(12)))
print("\n  sample usable games:")
n=0
for g in games:
    if g.get("winner_clan_name") and g.get("loser_clan_name") and g.get("map_name"):
        print(f"    {g.get('begin_at','')[:10]} {g['map_name']:<12} WIN:{g['winner_clan_name'][:18]:<19} "
              f"LOSE:{g['loser_clan_name'][:18]:<19} score {g.get('winner_clan_score')}-{g.get('loser_clan_score')} v{g.get('game_version')}")
        n+=1
        if n>=8: break
