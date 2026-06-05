import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
D = ROOT/"cowork_snapshot"/"gamedata"/"bo3"
for f in ["teams","matches","games"]:
    p = D/f"{f}.jsonl"
    if not p.exists(): print(f"{f}: (none yet)"); continue
    lines = p.read_text(encoding="utf-8").splitlines()
    print(f"{f}: {len(lines)} rows")
# sample a finished match + its games to verify winner derivation
mp = D/"matches.jsonl"
if mp.exists():
    matches = [json.loads(l) for l in mp.read_text(encoding="utf-8").splitlines()[:2000]]
    fin = [m for m in matches if m.get("status")=="finished" and m.get("maps_score")]
    if fin:
        m = fin[0]
        print("\nsample finished match fields:", {k:m.get(k) for k in ["id","team1_id","team2_id","winner_team_id","team1_score","team2_score","maps_score","bo_type","game_version","tier","start_date"]})
gp = D/"games.jsonl"
if gp.exists():
    games = [json.loads(l) for l in gp.read_text(encoding="utf-8").splitlines()[:2000]]
    g = games[0]
    print("\nsample game fields:", {k:g.get(k) for k in ["id","match_id","number","map_name","winner_clan_name","loser_clan_name","winner_clan_score","loser_clan_score","state","begin_at","game_version"]})
    # map_name distribution
    from collections import Counter
    c = Counter(g.get("map_name") for g in games)
    print("\nmap_name counts (first 2000 games):", dict(c.most_common(12)))
