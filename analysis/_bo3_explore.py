import requests, json
S = requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
                  "Accept":"application/json"})
def g(url, params=None, show=600):
    try:
        r = S.get(url, params=params, timeout=15)
        print(f"\n[{r.status_code}] {url}  params={params}")
        if r.status_code==200:
            try:
                j = r.json()
                print("  top keys:", list(j.keys())[:12] if isinstance(j,dict) else f"list[{len(j)}]")
                print("  sample:", json.dumps(j, default=str)[:show])
                return j
            except Exception:
                print("  (non-json)", r.text[:200])
    except Exception as e:
        print(f"  ERR {e}")
    return None

# explore the matches endpoint structure
j = g("https://api.bo3.gg/api/v1/matches", {"page[limit]":2})
# try filters for finished matches w/ results, and live
g("https://api.bo3.gg/api/v1/matches", {"filter[matches.status_id]":"3","page[limit]":1})
# look for a single match detail (maps/veto)
if j:
    # try to find a match id
    data = j.get("data") if isinstance(j,dict) else None
    if data and len(data):
        mid = data[0].get("id")
        slug = data[0].get("attributes",{}).get("slug") if isinstance(data[0].get("attributes"),dict) else None
        print("\n--- first match id:", mid, "slug:", slug)
        g(f"https://api.bo3.gg/api/v1/matches/{mid}")
# common esports-data endpoints
for ep in ["games","teams","tournaments","matches/upcoming","matches/live"]:
    g(f"https://api.bo3.gg/api/v1/{ep}", {"page[limit]":1})
