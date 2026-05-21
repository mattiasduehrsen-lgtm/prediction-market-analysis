"""What did the bot actually do today?"""
import json, datetime as dt
from pathlib import Path
from collections import Counter
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "esports_fade"
today_local = dt.datetime.now().date()
today_utc   = dt.datetime.now(dt.timezone.utc).date()
yest_utc    = today_utc - dt.timedelta(days=1)

print(f"Now (local): {dt.datetime.now()}  | Today (UTC): {today_utc}")
print()
print("=== Today's LIVE orders ===")
orders_today = []
with (OUT / "live_orders.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: o = json.loads(line)
        except: continue
        ts = float(o.get("ts") or 0)
        if not ts: continue
        d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
        if d == today_utc:
            orders_today.append(o)
print(f"  {len(orders_today)} order events today (UTC)")
for o in orders_today[-10:]:
    ts = float(o.get("ts") or 0)
    t = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%H:%M:%S")
    print(f"  {t}  {o.get('side','?')}  {o.get('status','?'):<10} ${o.get('cost_usd','?')}  {o.get('fade_slug','')[:42]}")

print()
print("=== fade_events.jsonl: recent type counts ===")
# Count event types since 24h ago
cutoff = dt.datetime.now(dt.timezone.utc).timestamp() - 86400
types_24h = Counter()
last_event_ts = 0
with (OUT / "fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        ts = float(e.get("timestamp") or e.get("ts") or 0)
        if ts > cutoff:
            types_24h[e.get("type","?")] += 1
        if ts > last_event_ts:
            last_event_ts = ts
for t, c in types_24h.most_common():
    print(f"  {c:>5}  {t}")
print()
if last_event_ts:
    age = dt.datetime.now(dt.timezone.utc).timestamp() - last_event_ts
    print(f"  Last event was {age:.0f}s ago ({dt.datetime.fromtimestamp(last_event_ts, tz=dt.timezone.utc):%H:%M:%S UTC})")

print()
print("=== Dashboard ===")
try:
    r = requests.get("http://localhost:5000/", timeout=5)
    print(f"  {r.status_code} OK  ({len(r.content)} bytes)")
except Exception as e:
    print(f"  DOWN: {e}")

print()
print("=== Last 15 LIVE order events (with timestamps) ===")
with (OUT / "live_orders.jsonl").open(encoding="utf-8") as f:
    lines = f.readlines()
for line in lines[-15:]:
    try: o = json.loads(line)
    except: continue
    ts = float(o.get("ts") or 0)
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%m-%d %H:%M UTC") if ts else "?"
    print(f"  {when}  {o.get('side','?'):<4} {o.get('status','?'):<10} ${o.get('cost_usd',0):.2f}  {o.get('fade_slug','')[:42]}")

print()
print("=== ALL event types in last 24h ===")
cutoff24 = dt.datetime.now(dt.timezone.utc).timestamp() - 86400
all_counts = Counter()
strat_counts = Counter()
entry_below_floor = 0
with (OUT / "fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        ts = float(e.get("timestamp") or e.get("ts") or 0)
        if ts < cutoff24: continue
        all_counts[e.get("type","?")] += 1
        if e.get("type") == "fade_signal":
            strat_counts[e.get("strategy","?")] += 1
            try:
                if float(e.get("our_entry") or 0) < 0.40:
                    entry_below_floor += 1
            except (TypeError, ValueError):
                pass
for t, c in all_counts.most_common():
    print(f"  {c:>5}  {t}")
print()
print(f"  fade_signal split: {dict(strat_counts)}")
print(f"  fade_signals with our_entry<0.40 (would be live-filtered): {entry_below_floor}")

print()
print("=== Pause flag check ===")
for p in (ROOT / "output/5m_live/paused.live.flag",):
    print(f"  {p.name}: {'EXISTS' if p.exists() else 'absent'}")
es_paused = OUT / "paused.flag"
if es_paused.exists():
    print(f"  esports_fade/paused.flag: EXISTS")
