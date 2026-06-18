"""Why isn't the LIVE esports bot trading? Aggregate fade_events.jsonl over the
last N hours: count signals and every skip reason. For model-unmatched skips,
separate real series-moneyline markets (fixable) from prop markets (totals/
handicap/single-map we intentionally don't trade). Run on the laptop."""
import json, time, re
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
EV = ROOT / "output" / "esports_fade" / "fade_events.jsonl"
HOURS = 48
cutoff = time.time() - HOURS * 3600

PROP = re.compile(r"-game\d|-map-?\d|total-games|round-total|handicap|-total-|over-under")
def is_series(slug):  # series moneyline = the markets we actually fade
    return bool(slug) and not PROP.search(slug)

types = Counter()
model_unmatched_series = Counter()   # slug -> count (fixable misses)
model_unmatched_prop = 0
signals = 0
placed = 0
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
        if t in ("onchain_signal", "signal"):
            signals += 1
        if t in ("live_order_placed",):
            placed += 1
        if t == "skip_model_unmatched":
            slug = e.get("slug", "")
            if is_series(slug):
                model_unmatched_series[slug] += 1
            else:
                model_unmatched_prop += 1

print(f"=== last {HOURS}h of fade_events ===")
print(f"signals seen: {signals} | live orders placed: {placed}\n")
print("event/skip type counts:")
for t, c in types.most_common():
    print(f"  {t:<28} {c}")
print(f"\nmodel_unmatched on PROP markets (correctly skipped): {model_unmatched_prop}")
print(f"model_unmatched on SERIES markets (these are the misses): "
      f"{sum(model_unmatched_series.values())} across {len(model_unmatched_series)} matchups")
for slug, c in model_unmatched_series.most_common(20):
    print(f"  {slug:<55} x{c}")
