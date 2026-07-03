import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "cowork_snapshot" / "gamedata" / "bo3" / "matches.jsonl"
mx = ""; last = []
with p.open(encoding="utf-8") as f:
    for line in f:
        try: m = json.loads(line)
        except Exception: continue
        sd = (m.get("start_date") or "")[:10]
        if sd > mx: mx = sd
        last.append((sd, m.get("status"), (m.get("slug") or "")[:44]))
print("max start_date in dump:", mx)
print("last 6 appended rows (today's run):")
for r in last[-6:]: print("  ", r)
