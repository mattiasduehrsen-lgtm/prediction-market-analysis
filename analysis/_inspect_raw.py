"""Dump the structure of one raw PandaScore match (cs2/lol) so we know the full
feature space available for modeling. Run on the laptop."""
import json, sys
from pathlib import Path

game = sys.argv[1] if len(sys.argv) > 1 else "lol"
ROOT = Path(r"C:\Users\matti\Desktop\prediction-market-analysis")
RAW = ROOT / "cowork_snapshot" / "gamedata" / "pandascore" / f"{game}_matches_raw.jsonl"

def shape(v, depth=0):
    if isinstance(v, dict):
        return {k: shape(val, depth+1) for k, val in v.items()} if depth < 3 else "{...}"
    if isinstance(v, list):
        return [shape(v[0], depth+1)] if v else []
    return type(v).__name__

# find a finished match with games/players populated
with RAW.open(encoding="utf-8") as f:
    best = None
    for i, line in enumerate(f):
        if i > 2000: break
        try: m = json.loads(line)
        except Exception: continue
        if m.get("status") == "finished" and (m.get("games") or m.get("opponents")):
            best = m
            if m.get("games") and any(g.get("players") for g in (m.get("games") or [])):
                break
if not best:
    print("no suitable match found"); sys.exit()
print(f"=== {game} raw match top-level keys ===")
print(sorted(best.keys()))
print("\n=== structure (types) ===")
print(json.dumps(shape(best), indent=1)[:3500])
print("\n=== sample values for modeling-relevant fields ===")
for k in ["number_of_games", "match_type", "status", "winner_id", "draw", "forfeit",
          "rescheduled", "detailed_stats", "live", "games", "results", "league",
          "serie", "tournament"]:
    v = best.get(k)
    if isinstance(v, (list, dict)):
        v = f"<{type(v).__name__} len={len(v)}>"
    print(f"  {k}: {v}")
g0 = (best.get("games") or [None])[0]
if g0:
    print("\n=== one game/map object keys ===")
    print(sorted(g0.keys()))
    print("  has players:", bool(g0.get("players")), "| winner:", g0.get("winner"),
          "| length:", g0.get("length"))
