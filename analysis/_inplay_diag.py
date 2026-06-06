import requests
from collections import Counter
S=requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json"})
def g(p,par=None):
    r=S.get(f"https://api.bo3.gg/api/v1/{p}",params=par,timeout=12)
    return r.json() if r.status_code==200 else None
# What the bot uses for status: matches sorted -start_date limit 50
m=(g("matches",{"sort":"-start_date","page[limit]":50}) or {}).get("results") or []
print("statuses in top-50 by -start_date (what bot uses for bo_by_id):")
print(" ",dict(Counter(x.get("status") for x in m)))
print("  date range:", m[-1].get("start_date","")[:10], "->", m[0].get("start_date","")[:10])
# Recent games -> live ones
gm=(g("games",{"sort":"-begin_at","page[limit]":100}) or {}).get("results") or []
live_games=[x for x in gm if x.get("state") in ("current","started","live")]
print(f"\nrecent 100 games: {len(live_games)} with live state")
live_mids=set(x.get("match_id") for x in live_games)
print("live match_ids from games:", list(live_mids)[:10])
# Are those live match_ids present in the -start_date top50 the bot keys on?
top50_ids=set(x.get("id") for x in m)
print("live match_ids ALSO in bot's match dict:", [mid for mid in live_mids if mid in top50_ids])
# Try fetching one live match directly
if live_mids:
    mid=list(live_mids)[0]
    d=g(f"matches/{mid}")
    if d:
        r=d.get("results") or d
        print(f"\n/matches/{mid} direct fetch -> status={r.get('status')} bo_type={r.get('bo_type')} "
              f"teams={r.get('team1_id')},{r.get('team2_id')}")
    else:
        print(f"\n/matches/{mid} direct fetch FAILED")
