"""Forensics on today's drought: when did orders stop, what events fired, did
stall detection / Telegram alerts trigger as expected."""
import json, time, datetime as dt
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "esports_fade"

now = time.time()
today_utc = dt.datetime.now(dt.timezone.utc).date()
day_start = dt.datetime(today_utc.year, today_utc.month, today_utc.day, tzinfo=dt.timezone.utc).timestamp()

print(f"Now: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC}")
print(f"Today UTC start: {dt.datetime.fromtimestamp(day_start, tz=dt.timezone.utc):%H:%M UTC}")
print()

# 1. All LIVE orders today, ordered chronologically
print("=" * 70)
print("ALL LIVE BUY orders today (UTC)")
print("=" * 70)
orders_today = []
with (OUT / "live_orders.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: o = json.loads(line)
        except: continue
        ts = float(o.get("ts") or 0)
        if ts < day_start: continue
        if str(o.get("side","BUY")).upper() != "BUY": continue
        orders_today.append(o)
prev_ts = day_start
for o in orders_today:
    ts = float(o.get("ts") or 0)
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%H:%M:%S")
    gap_min = (ts - prev_ts) / 60
    gap_str = f"+{gap_min:.0f}min gap" if gap_min > 30 else ""
    print(f"  {when} UTC  {o.get('status','?'):<10} ${o.get('cost_usd',0):.2f}  {o.get('fade_slug','')[:36]:<36}  {gap_str}")
    prev_ts = ts
final_gap_min = (now - prev_ts) / 60
print(f"  (now)         gap since last order: {final_gap_min:.0f}min")
print()

# 2. Events today by hour
print("=" * 70)
print("EVENTS PER HOUR (UTC) — what was the bot doing?")
print("=" * 70)
by_hour = {}  # hour_str -> Counter
with (OUT / "fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        ts = float(e.get("ts") or 0)
        if ts < day_start: continue
        hour = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%H:00")
        by_hour.setdefault(hour, Counter())[e.get("type","?")] += 1

# Find first hour with any event so we can show range
hours = sorted(by_hour.keys())
print(f"  {'hour':>8}  {'fade_signal':>12}  {'live_placed':>12}  {'live_final':>12}  {'stale_skip':>12}  {'risk_skip':>10}  {'stall':>6}")
for h in hours:
    c = by_hour[h]
    fs = c.get("fade_signal", 0)
    lp = c.get("live_order_placed", 0)
    lf = c.get("live_order_final", 0)
    ss = c.get("skip_stale_trade", 0)
    rs = c.get("skip_daily_risk_cap", 0)
    stall_evts = c.get("signal_stall_detected", 0) + c.get("signal_stall_recovered", 0)
    print(f"  {h:>8}  {fs:>12}  {lp:>12}  {lf:>12}  {ss:>12}  {rs:>10}  {stall_evts:>6}")
print()

# 3. Stall events specifically
print("=" * 70)
print("STALL events today")
print("=" * 70)
stalls = []
with (OUT / "fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        ts = float(e.get("ts") or 0)
        if ts < day_start: continue
        if "stall" in e.get("type",""):
            stalls.append(e)
if not stalls:
    print("  No stall events today.")
for e in stalls:
    ts = float(e.get("ts") or 0)
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%H:%M:%S")
    dur = e.get("stall_seconds")
    print(f"  {when} UTC  {e.get('type')}  duration={dur}s ({(dur or 0)/3600:.1f}h)")
print()

# 4. Bot startups today
print("=" * 70)
print("Bot startups today")
print("=" * 70)
wd_log = ROOT / "watchdog_esports.log"
if wd_log.exists():
    starts = []
    for line in wd_log.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Starting esports_fade_bot" in line:
            starts.append(line)
    for s in starts[-10:]:
        print(f"  {s.strip()}")
