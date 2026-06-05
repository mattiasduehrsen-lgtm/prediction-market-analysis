import json, time
from pathlib import Path
from collections import Counter
ROOT = Path(__file__).resolve().parents[1]
ev = ROOT/"output"/"esports_fade"/"fade_events.jsonl"
cut = time.time() - 48*3600
types = Counter()
passes=[]; rejects=[]
for line in ev.open(encoding="utf-8"):
    try: e=json.loads(line)
    except: continue
    if (e.get("ts") or 0) < cut: continue
    t=e.get("type","?"); types[t]+=1
    if t=="model_filter_pass": passes.append(e)
    if t=="skip_model_filter": rejects.append(e)
print("=== fade-bot events, last 48h ===")
for t,c in types.most_common():
    print(f"  {c:>5}  {t}")
# live orders placed in last 48h
lo = ROOT/"output"/"esports_fade"/"live_orders.jsonl"
placed=0; matched=0; recent=[]
if lo.exists():
    for line in lo.open(encoding="utf-8"):
        try: o=json.loads(line)
        except: continue
        if (o.get("ts") or 0) < cut: continue
        placed+=1
        if str(o.get("status","")).lower()=="matched": matched+=1
        recent.append(o)
print(f"\n=== live orders placed last 48h: {placed} (matched={matched}) ===")
for o in recent[-8:]:
    print(f"  {time.strftime('%m-%d %H:%M',time.localtime(o.get('ts',0)))} {o.get('side')} "
          f"{str(o.get('our_outcome'))[:18]} @{o.get('price')} status={o.get('status')} {str(o.get('slug',''))[:30]}")
print(f"\n=== model filter passes last 48h: {len(passes)} ===")
for e in passes[-10:]:
    print(f"  {time.strftime('%m-%d %H:%M',time.localtime(e['ts']))} {e.get('our_outcome')} edge={e.get('model_edge')} {str(e.get('slug'))[:30]}")
