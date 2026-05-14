"""Probe Polymarket APIs for May 13 ETH trade. Try multiple endpoints."""
import os, requests, json
from dotenv import load_dotenv
load_dotenv()

ADDR = os.environ["POLYMARKET_PROXY_ADDRESS"]
print(f"Probing for {ADDR}\n")

# A. data-api /trades with date filter
for params in [
    {"user": ADDR, "limit": 500},
    {"user": ADDR, "limit": 500, "offset": 90},
    {"user": ADDR, "limit": 100, "filterType": "FILL"},
    {"user": ADDR, "limit": 100, "side": "BUY"},
    {"user": ADDR, "limit": 100, "market_resolution": "RESOLVED"},
]:
    try:
        r = requests.get("https://data-api.polymarket.com/trades", params=params, timeout=10)
        print(f"GET /trades {params} -> {r.status_code} len={len(r.json()) if r.status_code==200 else '-'}")
        if r.status_code == 200 and r.json():
            sample = r.json()[0]
            print(f"  sample timestamp: {sample.get('timestamp')}")
    except Exception as e:
        print(f"  FAIL: {e}")

# B. /positions
try:
    r = requests.get("https://data-api.polymarket.com/positions", params={"user": ADDR, "limit": 200}, timeout=10)
    print(f"\nGET /positions -> {r.status_code} len={len(r.json()) if r.status_code==200 else '-'}")
    if r.status_code == 200:
        for p in r.json()[:10]:
            print(f"  cond={p.get('conditionId','?')[:14]}  shares={p.get('size','?')}  redeemable={p.get('redeemable','?')}  slug={p.get('slug','?')[:40]}")
except Exception as e:
    print(f"FAIL: {e}")

# C. /activity
try:
    r = requests.get("https://data-api.polymarket.com/activity", params={"user": ADDR, "limit": 100}, timeout=10)
    print(f"\nGET /activity -> {r.status_code} len={len(r.json()) if r.status_code==200 else '-'}")
    if r.status_code == 200 and r.json():
        for a in r.json()[:5]:
            print(f"  {a.get('timestamp','?')}  {a.get('type','?')}  {a.get('side','?')}  slug={a.get('slug','?')[:40]}")
except Exception as e:
    print(f"FAIL: {e}")
