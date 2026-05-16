"""Quick audit of live_orders.jsonl — counts, totals, consistency check."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSONL = ROOT / "output" / "esports_fade" / "live_orders.jsonl"
if not JSONL.exists():
    print("no live_orders.jsonl"); raise SystemExit

rows = [json.loads(l) for l in JSONL.open(encoding="utf-8") if l.strip()]
print(f"total rows: {len(rows)}\n")

c = Counter((r.get("side", "BUY"), r.get("status", "").lower()) for r in rows)
print("by (side, status):")
for k in sorted(c.keys()):
    print(f"  {k[0]:<5} {k[1]:<12} {c[k]:>4}")
print()

buys = [r for r in rows if r.get("side", "BUY") == "BUY"]
sells = [r for r in rows if r.get("side", "BUY") == "SELL"]
buys_matched = [r for r in buys if r.get("status", "").lower() == "matched"]
sells_matched = [r for r in sells if r.get("status", "").lower() == "matched"]

total_buy_cost = sum(float(r.get("cost_usd") or 0) for r in buys_matched)
total_sell_proceeds = sum(float(r.get("cost_usd") or 0) for r in sells_matched)
print(f"matched BUYs:  {len(buys_matched)}  total cost     = ${total_buy_cost:.2f}")
print(f"matched SELLs: {len(sells_matched)}  total proceeds = ${total_sell_proceeds:.2f}")
print(f"net so far (excl. unresolved): ${total_sell_proceeds - total_buy_cost:+.2f}")
print()

# Sanity: are there any rows missing fields?
missing = []
for r in rows:
    if r.get("side", "BUY") == "BUY":
        needed = ["token_id", "fade_condition", "our_outcome", "price", "shares"]
    else:
        needed = ["token_id", "price", "shares"]
    for f in needed:
        if not r.get(f):
            missing.append(f"  {r.get('order_id','?')[:18]}... missing {f}")
            break
if missing:
    print(f"rows with missing fields: {len(missing)}")
    for m in missing[:10]:
        print(m)
else:
    print("all rows have required fields")
print()

# Are there duplicate order_ids? (would indicate a logging bug)
oids = [r.get("order_id", "") for r in rows]
dupes = [oid for oid, cnt in Counter(oids).items() if cnt > 1 and oid]
if dupes:
    print(f"DUPLICATE order_ids: {len(dupes)}")
    for d in dupes[:5]:
        print(f"  {d[:30]}...")
else:
    print("no duplicate order_ids")
