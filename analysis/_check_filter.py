import json, time
from pathlib import Path
from collections import Counter
ROOT = Path(__file__).resolve().parents[1]
f = ROOT/"output"/"esports_fade"/"fade_events.jsonl"
cutoff = time.time() - 3*3600   # last 3 hours
types = Counter()
model_events = []
for line in f.open(encoding="utf-8"):
    try: e = json.loads(line)
    except: continue
    if (e.get("ts") or 0) < cutoff: continue
    t = e.get("type","?")
    types[t] += 1
    if t.startswith(("skip_model","model_filter")):
        model_events.append(e)
print("=== event types (last 3h) ===")
for t,c in types.most_common():
    print(f"  {c:>5}  {t}")
print(f"\n=== model-filter events (last 3h): {len(model_events)} ===")
for e in model_events[-12:]:
    ts = time.strftime("%H:%M", time.localtime(e.get("ts",0)))
    print(f"  {ts} {e.get('type')}: slug={str(e.get('slug'))[:40]} "
          f"our={e.get('our_outcome')} entry={e.get('our_entry')} "
          f"model_p={e.get('model_p')} edge={e.get('model_edge')} reason={e.get('reason','')}")
