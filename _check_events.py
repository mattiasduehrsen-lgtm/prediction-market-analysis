"""Quick: what events has the bot been writing recently?"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ev = ROOT / "output" / "esports_fade" / "fade_events.jsonl"

# Look at the last 1000 events
lines = ev.read_text(encoding="utf-8").splitlines()[-1000:]
print(f"Analyzing last {len(lines)} events")

counts = Counter()
stale_ages = []
recent_fades = []
recent_stale_count = 0
for line in lines:
    try: e = json.loads(line)
    except: continue
    t = e.get("type", "?")
    counts[t] += 1
    if t == "skip_stale_trade":
        stale_ages.append(e.get("age_s", 0))
        recent_stale_count = e.get("count_so_far", recent_stale_count)
    elif t == "fade_signal":
        recent_fades.append({
            "strategy": e.get("strategy"),
            "their_fill_ts": e.get("their_fill_ts"),
            "signal_seen_at": e.get("signal_seen_at"),
            "lag_s": e.get("signal_lag_s"),
            "our_entry": e.get("our_entry"),
        })

print()
print("Event types:")
for t, c in counts.most_common():
    print(f"  {c:>4}  {t}")

print()
print(f"Cumulative skip_stale_trade count (from last logged event): {recent_stale_count}")
print(f"skip_stale_trade events captured in last 1000 lines: {len(stale_ages)}")
if stale_ages:
    print(f"  ages_s sample (one logged per 100 skips): {stale_ages}")

print()
print(f"Last 5 fade_signal events:")
for f in recent_fades[-5:]:
    print(f"  strategy={f['strategy']:>6}  lag_s={f['lag_s']}  our_entry={f['our_entry']}")

# Check daily_risk_usd: sum live_orders.jsonl matched BUYs since last UTC midnight
import datetime as dt
midnight = dt.datetime.combine(dt.datetime.utcnow().date(), dt.time.min, tzinfo=dt.timezone.utc).timestamp()
orders_today = []
with (ROOT / "output" / "esports_fade" / "live_orders.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: o = json.loads(line)
        except: continue
        if (o.get("ts") or 0) < midnight: continue
        if str(o.get("side","BUY")).upper() != "BUY": continue
        orders_today.append(o)
print()
print(f"=== Today UTC ({dt.datetime.utcnow().date()}) ===")
matched_buys = [o for o in orders_today if str(o.get("status","")).lower() == "matched"]
canceled = [o for o in orders_today if str(o.get("status","")).lower() in ("canceled","cancelled")]
print(f"  matched BUYs   : {len(matched_buys)}, cost sum=${sum(float(o.get('cost_usd') or 0) for o in matched_buys):.2f}")
print(f"  canceled BUYs  : {len(canceled)}")

# Inspect what skip_daily_risk_cap was reporting
last_risk_skip = None
with (ROOT / "output" / "esports_fade" / "fade_events.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        if e.get("type") == "skip_daily_risk_cap":
            last_risk_skip = e
print()
print(f"Last skip_daily_risk_cap event:")
print(f"  {last_risk_skip}")
