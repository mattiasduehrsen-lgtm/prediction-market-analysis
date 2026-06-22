"""Test which Polygon RPCs work right now (Alchemy cap reset? public nodes alive?).
Masks the Alchemy key. Run on the laptop."""
import os, time
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
PUBLIC = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
    "https://polygon.llamarpc.com",
    "https://polygon.drpc.org",
    "https://1rpc.io/matic",
]
env = os.environ.get("POLYGON_RPC_URL", "").strip()
urls = ([env] if env else []) + PUBLIC

def mask(u):
    return u.split("/v2/")[0] + "/v2/***" if "/v2/" in u else u

payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
for u in urls:
    t0 = time.time()
    try:
        r = requests.post(u, json=payload, timeout=10)
        dt = (time.time() - t0) * 1000
        body = r.text[:80].replace("\n", " ")
        ok = r.status_code == 200 and "result" in r.text
        print(f"  [{r.status_code}] {'OK ' if ok else 'BAD'} {dt:5.0f}ms  {mask(u)}  {'' if ok else body}")
    except Exception as e:
        print(f"  [ERR] {mask(u)}  {str(e)[:80]}")
