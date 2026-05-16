"""Verify that JSONL rows with status='live' are actually off-book now."""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from src.bot.clob_auth import get_client

c = get_client()
print(f"Open orders on Polymarket right now: {len(c.get_open_orders())}\n")

rows = [json.loads(l) for l in (ROOT / "output/esports_fade/live_orders.jsonl").open(encoding="utf-8") if l.strip()]
live_rows = [r for r in rows if r.get("side","BUY")=="BUY" and r.get("status","").lower()=="live"]
print(f"JSONL rows with status=live: {len(live_rows)}")
for r in live_rows:
    oid = r.get("order_id","")
    if not oid: continue
    try:
        o = c.get_order(oid)
        print(f"  {oid[:24]}...  actual status: {str(o.get('status','?')).lower()}  matched: {o.get('size_matched','0')}")
    except Exception as e:
        print(f"  {oid[:24]}...  query err: {type(e).__name__}: {e}")
