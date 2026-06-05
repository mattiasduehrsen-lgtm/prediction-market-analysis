import requests, json
S = requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 Chrome/120 Safari/537.36","Accept":"application/json"})
def g(url, params=None):
    r = S.get(url, params=params, timeout=15)
    return r.status_code, (r.json() if r.status_code==200 else r.text[:200])

# 1. recent matches sorted desc -> find live/upcoming statuses
sc, j = g("https://api.bo3.gg/api/v1/matches", {"sort":"-start_date","page[limit]":15})
print("=== most recent 15 matches: statuses + map progress ===")
statuses=set()
live_id=None
for m in (j.get("results") or []):
    st=m.get("status"); statuses.add(st)
    print(f"  {m.get('start_date','')[:16]}  status={st:<10} bo{m.get('bo_type')} "
          f"score={m.get('team1_score')}-{m.get('team2_score')} maps_score={m.get('maps_score')} "
          f"{m.get('slug','')[:45]}")
    if st in ("live","current","running","started") and not live_id:
        live_id=m.get("id")
print("  distinct statuses seen:", statuses)

# 2. full game object — does it carry per-map ROUND score (for in-map live edge)?
sc,j = g("https://api.bo3.gg/api/v1/games", {"sort":"-begin_at","page[limit]":1})
if j.get("results"):
    gm=j["results"][0]
    print("\n=== newest game object — all fields ===")
    for k,v in gm.items():
        if k=="demo_header": 
            print(f"  demo_header: <present>")
            continue
        print(f"  {k}: {str(v)[:80]}")

# 3. try to find a currently-live match by filtering status
print("\n=== probing for live matches via status filter ===")
for stat in ["live","current","running"]:
    sc,j = g("https://api.bo3.gg/api/v1/matches", {"filter[matches.status]":stat,"page[limit]":3})
    n = j.get("total",{}).get("count") if isinstance(j,dict) else "?"
    print(f"  status={stat}: count={n}")
    if isinstance(j,dict) and j.get("results"):
        for m in j["results"][:2]:
            print(f"     live: {m.get('slug','')[:50]} maps_score={m.get('maps_score')}")
            # pull that match's games to see map order + current map state
            sc2,jg = g("https://api.bo3.gg/api/v1/games", {"filter[games.match_id]":m.get('id'),"sort":"begin_at"})
            for ggame in (jg.get("results") or []):
                print(f"        map={ggame.get('map_name')} state={ggame.get('state')}")
