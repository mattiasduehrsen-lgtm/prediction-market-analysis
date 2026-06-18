"""What happens at the LIVE order step? Reads fade_events.jsonl over the last N
minutes, counts every event type, and dumps the full lines of placement-related
events (live_order_placed / live_order_error / live_skip_* / skip_entry_price_floor)
so we can see whether place_live_order is being reached and why it fails. Laptop."""
import json, sys, time
from collections import Counter
from pathlib import Path

MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 60
ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
EV = ROOT / "output" / "esports_fade" / "fade_events.jsonl"
cutoff = time.time() - MIN * 60

types = Counter()
interesting = []
KEYS = ("live_order_placed", "live_order_error", "live_skip", "skip_entry_price_floor",
        "model_filter_pass", "fade_signal", "live_order_status")
with EV.open(encoding="utf-8") as f:
    for line in f:
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("ts", 0) < cutoff:
            continue
        t = e.get("type", "?")
        types[t] += 1
        if any(k in t for k in KEYS):
            interesting.append(line.strip())

print(f"=== last {MIN} min ===")
for t, c in types.most_common():
    print(f"  {t:<28} {c}")
print(f"\n--- last 12 placement-related events ---")
for l in interesting[-12:]:
    print(l)
if not interesting:
    print("(none — no signal reached the placement step)")
