import requests, time
S = requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
tests = [
    ("HLTV.org (stats gold standard)", "https://www.hltv.org/", {}),
    ("HLTV results page", "https://www.hltv.org/results", {}),
    ("Liquipedia CS2 API (free, public)",
     "https://liquipedia.net/counterstrike/api.php",
     {"action":"query","format":"json","list":"recentchanges","rclimit":"1"}),
    ("bo3.gg", "https://bo3.gg/", {}),
    ("PandaScore (needs token; expect 401)", "https://api.pandascore.co/csgo/matches", {}),
    ("The Odds API (esports? needs key)", "https://api.the-odds-api.com/v4/sports/", {}),
    ("OddsPortal", "https://www.oddsportal.com/", {}),
]
for name, url, params in tests:
    try:
        r = S.get(url, params=params, timeout=12)
        body = ""
        ct = r.headers.get("content-type","")
        if "json" in ct:
            body = str(r.json())[:120]
        else:
            body = r.text[:80].replace("\n"," ")
        cf = "CLOUDFLARE" if ("cloudflare" in r.text.lower() or "cf-ray" in r.headers) else ""
        print(f"  [{r.status_code}] {name} {cf}")
        print(f"        {body}")
    except Exception as e:
        print(f"  [ERR] {name}: {e}")
    time.sleep(0.5)
