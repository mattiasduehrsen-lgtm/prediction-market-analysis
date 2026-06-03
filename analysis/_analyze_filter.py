import json, time
from pathlib import Path
from collections import Counter, defaultdict
ROOT = Path(__file__).resolve().parents[1]
ev_path = ROOT/"output"/"esports_fade"/"fade_events.jsonl"

MODEL_TYPES = {"model_filter_pass","skip_model_filter","skip_model_unmatched","skip_model_no_coverage"}
events = []
for line in ev_path.open(encoding="utf-8"):
    try: e = json.loads(line)
    except: continue
    events.append(e)

# Only events since the model filter first appeared
first_model_ts = None
for e in events:
    if e.get("type") in MODEL_TYPES:
        first_model_ts = e.get("ts"); break
if first_model_ts is None:
    print("No model-filter events yet."); raise SystemExit
since = [e for e in events if (e.get("ts") or 0) >= first_model_ts]

print(f"Since model filter live ({time.strftime('%Y-%m-%d %H:%M', time.localtime(first_model_ts))}):")
counts = Counter(e.get("type") for e in since)
# focus on the relevant decision points
for t in ["fade_signal","model_filter_pass","skip_model_filter","skip_model_unmatched",
          "skip_model_no_coverage","skip_single_map","skip_wallet_daily_cap",
          "skip_opposite_side_held","skip_entry_price_floor","live_order_placed"]:
    if counts.get(t): print(f"  {counts[t]:>4}  {t}")

print("\n=== PASSES (fades the model approved) ===")
passes = [e for e in since if e.get("type")=="model_filter_pass"]
for e in passes:
    print(f"  {time.strftime('%m-%d %H:%M',time.localtime(e['ts']))} {e.get('our_outcome')} "
          f"entry={e.get('our_entry')} model_p={e.get('model_p')} edge={e.get('model_edge')} "
          f"slug={str(e.get('slug'))[:38]}")
if not passes: print("  (none yet)")

print("\n=== LOW-EDGE REJECTIONS (model said our side not underpriced enough) ===")
rej = [e for e in since if e.get("type")=="skip_model_filter"]
edges = sorted(e.get("model_edge",0) for e in rej)
for e in rej[-10:]:
    print(f"  {time.strftime('%m-%d %H:%M',time.localtime(e['ts']))} {e.get('our_outcome')} "
          f"entry={e.get('our_entry')} model_p={e.get('model_p')} edge={e.get('model_edge'):+.3f} "
          f"slug={str(e.get('slug'))[:38]}")
if edges:
    print(f"  edge distribution of rejections: min={min(edges):+.3f} max={max(edges):+.3f} "
          f"(threshold=+0.10; max should be <=0.10)")
    near = [x for x in edges if 0.05 < x <= 0.10]
    neg = [x for x in edges if x <= 0]
    print(f"  rejected near-miss (0.05-0.10): {len(near)}   rejected negative-edge: {len(neg)}")

print("\n=== UNMATCHED (model couldn't rate a team — coverage gap) ===")
unm = [e for e in since if e.get("type")=="skip_model_unmatched"]
teams_missed = Counter()
for e in unm:
    teams_missed[f"{e.get('our_outcome')} / {e.get('other')}"] += 1
for k,c in teams_missed.most_common(10):
    print(f"  {c:>3}  {k}")
if not unm: print("  (none)")

print("\n=== NON-CS2 SKIPPED (LoL etc — no model) ===")
print(f"  {counts.get('skip_model_no_coverage',0)} skipped (correctly — model is CS2-only)")

# Sanity verdict
print("\n=== VERDICT ===")
total_eval = len(passes)+len(rej)+len(unm)
print(f"  Target fades that reached the model gate: {total_eval+counts.get('skip_model_no_coverage',0)}")
print(f"    passed: {len(passes)}  low-edge-rejected: {len(rej)}  unmatched: {len(unm)}  non-cs2: {counts.get('skip_model_no_coverage',0)}")
bad = [x for x in edges if x>0.10]
print(f"  Rejections with edge>threshold (SHOULD BE 0): {len(bad)}")
