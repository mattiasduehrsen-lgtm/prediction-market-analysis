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
