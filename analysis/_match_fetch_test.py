import requests
S=requests.Session(); S.headers.update({"User-Agent":"Mozilla/5.0","Accept":"application/json"})
def g(p,par=None):
    r=S.get(f"https://api.bo3.gg/api/v1/{p}",params=par,timeout=12)
    return (r.status_code, r.json() if r.status_code==200 else r.text[:150])
# get a recent match_id from recent games
gm=requests.get("https://api.bo3.gg/api/v1/games",params={"sort":"-begin_at","page[limit]":5},
                headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},timeout=12).json()["results"]
mid=gm[0]["match_id"]
print("test match_id:",mid)
sc,d=g(f"matches/{mid}")
print("GET /matches/{id} status:",sc)
if isinstance(d,dict):
    r=d.get("results") or d
    print("  fields:",{k:r.get(k) for k in ["id","status","bo_type","team1_id","team2_id","team1","team2"] if k in r})
    # team names?
    for tk in ["team1","team2"]:
        t=r.get(tk)
        if isinstance(t,dict): print(f"  {tk}: {t.get('name')}")
