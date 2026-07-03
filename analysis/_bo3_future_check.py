"""Why does tier_index have no future rows? Inspect upcoming matches in the bo3 dump."""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLUG = re.compile(r"^(.+)-vs-(.+)-(\d{2})-(\d{2})-(\d{4})$")
HASHY = re.compile(r"^[0-9a-f]{8,12}$")
n_fut = named = hashed = ids_ok = 0
samp = []
with (ROOT / "cowork_snapshot" / "gamedata" / "bo3" / "matches.jsonl").open(encoding="utf-8") as f:
    for line in f:
        try:
            m = json.loads(line)
        except Exception:
            continue
        sd = (m.get("start_date") or "")[:10]
        if sd < "2026-07-02":
            continue
        n_fut += 1
        slug = m.get("slug") or ""
        mm = SLUG.match(slug)
        if mm and not (HASHY.match(mm.group(1)) and HASHY.match(mm.group(2))):
            named += 1
        else:
            hashed += 1
        if m.get("team1_id") and m.get("team2_id"):
            ids_ok += 1
        if len(samp) < 8:
            samp.append((sd, slug[:58], m.get("team1_id"), m.get("team2_id"), m.get("tier")))
print(f"future matches: {n_fut} | named slugs: {named} | hashed/TBD: {hashed} | with team ids: {ids_ok}")
for s in samp:
    print("  ", s)
