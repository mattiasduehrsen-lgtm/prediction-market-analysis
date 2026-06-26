"""Summarize shadow A/B: Elo filter vs the esports_model Predictor on live CS2 fades.
Reads shadow_compare events from fade_events.jsonl. Today it reports agreement +
where they disagree; once those markets resolve, extend to who was right. Laptop."""
import json
from pathlib import Path
ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
EV = ROOT / "output" / "esports_fade" / "fade_events.jsonl"

rows = []
with EV.open(encoding="utf-8") as f:
    for line in f:
        if '"shadow_compare"' not in line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "shadow_compare":
            rows.append(e)

ok = [r for r in rows if r.get("shadow_ok")]
print(f"shadow_compare events: {len(rows)} | shadow model resolved a prob: {len(ok)} "
      f"| shadow unmatched: {len(rows)-len(ok)}")
if not ok:
    print("(no matched shadow predictions yet)"); raise SystemExit

agree = sum(1 for r in ok if r.get("agree_pass") == 1)
elo_pass = sum(1 for r in ok if r.get("elo_pass") == 1)
sh_pass = sum(1 for r in ok if r.get("shadow_pass") == 1)
print(f"both-models would-trade decision AGREE: {agree}/{len(ok)} ({agree/len(ok)*100:.0f}%)")
print(f"  Elo would-trade: {elo_pass} | shadow would-trade: {sh_pass}")
print("\ndisagreements (Elo vs shadow on whether to fade):")
dis = [r for r in ok if r.get("agree_pass") == 0]
for r in dis[-15:]:
    print(f"  {r.get('slug','')[:34]:34} our={r.get('our_outcome','')[:12]:12} "
          f"entry={r.get('our_entry')} | elo_p={r.get('elo_p')} edge={r.get('elo_edge')} pass={r.get('elo_pass')} "
          f"| shadow_p={r.get('shadow_p')} edge={r.get('shadow_edge')} pass={r.get('shadow_pass')}")
if not dis:
    print("  (none — models agree so far)")
print(f"\n{len(dis)} disagreements = the trades where the model would change behavior.")
print("Next: once these markets resolve, score which side was right (the go-live signal).")
