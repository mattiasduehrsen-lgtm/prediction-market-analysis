"""Watch the bot for new orders/events and print summary, filtered by time."""
import json, time, datetime as dt
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
EV = ROOT / "output" / "esports_fade" / "fade_events.jsonl"
ORDERS = ROOT / "output" / "esports_fade" / "live_orders.jsonl"

# Find the most recent bot start (look for startup events / use bot start time
# from watchdog log mtime as fallback). Simpler: look at events with ts in
# the last 5 min.
now = time.time()
cutoff = now - 300  # last 5 min

# Best timestamp field varies — use ts > 1e9 (epoch seconds), or any signal_seen_at
def event_ts(e):
    for k in ("ts", "signal_seen_at", "their_fill_ts", "timestamp"):
        v = e.get(k)
        if v and isinstance(v, (int, float)) and v > 1e9:
            return float(v)
    return 0.0

counts_5m = Counter()
counts_all = Counter()
with EV.open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        counts_all[e.get("type", "?")] += 1
        if event_ts(e) > cutoff:
            counts_5m[e.get("type", "?")] += 1

print(f"=== Events written in last 5 minutes ===")
if not counts_5m:
    print("  (none — bot is quiet or events don't have timestamps)")
for t, c in counts_5m.most_common():
    print(f"  {c:>4}  {t}")

print()
print(f"=== Recent matched live orders ===")
ord_lines = ORDERS.read_text(encoding="utf-8").splitlines()[-5:]
for line in ord_lines:
    try: o = json.loads(line)
    except: continue
    ts = float(o.get("ts") or 0)
    age_min = (now - ts) / 60 if ts else 0
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%m-%d %H:%M:%S") if ts else "?"
    print(f"  {when} UTC ({age_min:.1f} min ago)  {o.get('status','?'):<10} ${o.get('cost_usd',0):.2f}  {o.get('fade_slug','')[:40]}")

# Stall flag
stall = ROOT / "output" / "esports_fade" / "signal_stall.flag"
print()
print("Stall flag:", "EXISTS" if stall.exists() else "absent")
