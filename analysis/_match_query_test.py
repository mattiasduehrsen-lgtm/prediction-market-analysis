import requests
from datetime import datetime, timezone, timedelta
from collections import Counter
S=requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json"})
def g(par):
    r=S.get("https://api.bo3.gg/api/v1/matches",params=par,timeout=12)
    return r.status_code,(r.json() if r.status_code==200 else r.text[:120])
# get a real match id from games
mid=requests.get("https://api.bo3.gg/api/v1/games",params={"sort":"-begin_at","page[limit]":1},
                 headers={"User-Agent":"Mozilla/5.0"},timeout=12).json()["results"][0]["match_id"]
print("A) id filter on", mid)
sc,d=g({"filter[matches.id]":mid,"page[limit]":1})
print("  status",sc, "->", ([{k:x.get(k) for k in ['id','status','bo_type','team1_id','team2_id']} for x in d.get("results",[])][:1] if isinstance(d,dict) else d))
# range on start_date: last 8h -> now+1h (live + recent)
now=datetime.now(timezone.utc)
lo=(now-timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ"); hi=(now+timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
print("\nB) range[start_date] last 8h ->", )
sc,d=g({"range[start_date]":f"{lo},{hi}","sort":"-start_date","page[limit]":50})
rows=d.get("results",[]) if isinstance(d,dict) else []
print("  status",sc,"n=",len(rows),"statuses:",dict(Counter(x.get("status") for x in rows)))
for x in rows[:6]:
    print(f"    {x.get('start_date','')[:16]} status={x.get('status'):<9} bo{x.get('bo_type')} {x.get('slug','')[:40]}")
