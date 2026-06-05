# Quick feasibility probe BEFORE the full backtest: do Polymarket SERIES prices
# actually move enough mid-match to create in-play opportunity, and can we line
# up bo3 map-completion times with shard price history?
import json
from pathlib import Path
from collections import defaultdict
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
BO3 = ROOT/"cowork_snapshot"/"gamedata"/"bo3"
GD = ROOT/"cowork_snapshot"/"gamedata"

# bo3 timelines: match_id -> ordered maps (number, begin_at, winner, t1t2)
games = [json.loads(l) for l in (BO3/"games.jsonl").read_text(encoding="utf-8").splitlines()]
bym = defaultdict(list)
for g in games:
    if g.get("game_version")!=2: continue
    if not (g.get("winner_clan_name") and g.get("begin_at") and g.get("map_name")): continue
    bym[g.get("match_id")].append(g)
multi = {mid:gs for mid,gs in bym.items() if len(gs)>=2}
print(f"bo3 CS2 matches with >=2 maps (Bo3+): {len(multi)}")
# how many have distinct begin_at per map (so we can time map completions)?
timed=0
for mid,gs in list(multi.items())[:5000]:
    bts=set(g["begin_at"] for g in gs)
    if len(bts)==len(gs): timed+=1
print(f"  of first 5000: {timed} have distinct per-map begin_at (timeable)")
# sample a Bo3 timeline
for mid,gs in list(multi.items())[:3]:
    gs=sorted(gs,key=lambda x:(x.get("number") or 0))
    print(f"\n  match {mid}:")
    for g in gs:
        print(f"    map{g.get('number')} {g['map_name']:<11} {g['begin_at'][:16]} WIN:{g['winner_clan_name'][:16]}")
