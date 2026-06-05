import requests, time, json
S = requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"})
def check(name, url, params=None, markers=None):
    try:
        r = S.get(url, params=params, timeout=15)
        body = r.text
        cf = any(x in body.lower() for x in ["just a moment","challenge-platform","cf-mitigated","enable javascript and cookies"])
        hits = [m for m in (markers or []) if m.lower() in body.lower()]
        print(f"[{r.status_code}] {name}  len={len(body)}  cloudflare={cf}  found={hits}")
    except Exception as e:
        print(f"[ERR] {name}: {e}")
    time.sleep(0.6)

print("=== HLTV (per-map team stats + live) ===")
check("HLTV team maps stats", "https://www.hltv.org/stats/teams/maps/4608/natus-vincere", markers=["Mirage","Inferno","Win rate","Nuke"])
check("HLTV matches (live/upcoming)", "https://www.hltv.org/matches", markers=["LIVE","Best of","bestof"])
check("HLTV results", "https://www.hltv.org/results", markers=["Mirage","map"])

print("\n=== bo3.gg JSON API (unofficial) ===")
check("bo3 api matches", "https://api.bo3.gg/api/v1/matches", markers=["data","attributes"])

print("\n=== Liquipedia MediaWiki API (free) ===")
# search for CS2 match pages
check("Liquipedia search CS2 matches", "https://liquipedia.net/counterstrike/api.php",
      params={"action":"query","list":"search","srsearch":"Mirage incategory:Matches","format":"json","srlimit":3},
      markers=["search","title"])

print("\n=== Community / unofficial live CS2 score APIs ===")
check("HLTV scorebot config", "https://www.hltv.org/matches/2380000/x", markers=["scorebot","Best of"])
check("esportsbattle/strafe", "https://strafe.com/", markers=["match","live"])

print("\n=== Valve / GOTV-related ===")
print("(GOTV requires CS2 client connect to a relay IP per match — not an HTTP check)")

print("\n=== demoparser2 (parse .dem demos for perfect per-map data) ===")
import importlib.util
for lib in ["demoparser2","awpy"]:
    spec = importlib.util.find_spec(lib)
    print(f"  {lib}: {'INSTALLED' if spec else 'not installed (on PyPI: pip install '+lib+')'}")
