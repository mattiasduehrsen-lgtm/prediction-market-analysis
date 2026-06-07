import requests
from collections import Counter
S=requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json"})
games=S.get("https://api.bo3.gg/api/v1/games",params={"sort":"-begin_at","page[limit]":100},timeout=15).json()["results"]
print("recent 100 games:")
print("  STATE field values :", dict(Counter(g.get('state') for g in games)))
print("  STATUS field values:", dict(Counter(g.get('status') for g in games)))
# live by status
live_status=[g for g in games if g.get("status") in ("current","started","live")]
live_state=[g for g in games if g.get("state") in ("current","started","live")]
print(f"\n  live by STATUS: {len(live_status)}   live by STATE: {len(live_state)}")
for g in live_status[:8]:
    print(f"    match={g.get('match_id')} map{g.get('number')} {g.get('map_name')} "
          f"state={g.get('state')} status={g.get('status')} "
          f"win={g.get('winner_clan_name')}")
