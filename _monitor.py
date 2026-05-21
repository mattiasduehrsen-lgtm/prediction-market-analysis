"""Watch the bot for new orders/events and print summary."""
import json, time, datetime as dt
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
EV = ROOT / "output" / "esports_fade" / "fade_events.jsonl"
ORDERS = ROOT / "output" / "esports_fade" / "live_orders.jsonl"

# Last 200 events
lines = EV.read_text(encoding="utf-8").splitlines()[-200:]
counts = Counter()
for line in lines:
    try: e = json.loads(line)
    except: continue
    counts[e.get("type", "?")] += 1
print(f"Last {len(lines)} events:")
for t, c in counts.most_common():
    print(f"  {c:>4}  {t}")

# Last 5 live orders
print()
print("Last 5 live order events:")
order_lines = ORDERS.read_text(encoding="utf-8").splitlines()[-5:]
for line in order_lines:
    try: o = json.loads(line)
    except: continue
    ts = float(o.get("ts") or 0)
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%m-%d %H:%M:%S") if ts else "?"
    print(f"  {when}  {o.get('side','?'):<4} {o.get('status','?'):<10} ${o.get('cost_usd',0):.2f}  {o.get('fade_slug','')[:40]}")

# Check signal_stall flag
stall = ROOT / "output" / "esports_fade" / "signal_stall.flag"
if stall.exists():
    print(f"\n⚠️ signal_stall.flag exists")
else:
    print(f"\n🟢 no stall flag")
