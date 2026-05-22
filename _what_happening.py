"""Quick: what's the bot been doing in the last 30 min?"""
import json, time, datetime as dt
from pathlib import Path
from collections import Counter

ev = Path(__file__).parent / "output" / "esports_fade" / "fade_events.jsonl"
cutoff = time.time() - 1800  # 30 min
counts = Counter()
recent = []
with ev.open(encoding="utf-8") as f:
    for line in f:
        try: e = json.loads(line)
        except: continue
        ts = float(e.get("ts") or 0)
        if ts < cutoff: continue
        counts[e.get("type","?")] += 1
        if e.get("type") in ("fade_signal", "skip_stale_target_trade",
                             "live_order_placed", "live_order_final", "live_order_error"):
            recent.append((ts, e))

print("Event types in last 30 min:")
for t, c in counts.most_common():
    print(f"  {c:>4}  {t}")

print()
print("Last 8 trade-related events:")
for ts, e in recent[-8:]:
    when = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%H:%M:%S UTC")
    t = e.get("type")
    if t == "fade_signal":
        summary = f"FADE_SIGNAL strat={e.get('strategy','?')} entry={e.get('our_entry','?')} slug={(e.get('fade_slug','') or '')[:30]}"
    elif t == "skip_stale_target_trade":
        summary = f"stale_target strat={e.get('strategy','?')} age={e.get('age_s','?')}s slug={(e.get('fade_slug','') or '')[:30]}"
    elif t == "live_order_placed":
        summary = f"order_placed status={e.get('status','?')} price={e.get('price','?')}"
    elif t == "live_order_final":
        summary = f"order_final status={e.get('status','?')} matched={e.get('matched','?')} cost={e.get('cost_usd','?')}"
    elif t == "live_order_error":
        summary = f"order_error err={(e.get('error','') or '')[:60]}"
    else:
        summary = t
    print(f"  {when}  {summary}")
