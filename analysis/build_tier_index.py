"""Build the LIVE tier index for the fade bot's bet_ok gate.

From the bo3 dump (weekly-refreshed, includes UPCOMING matches with tier), emit a
small parquet the bot can hot-load: normalized team pair + date -> tier_ord
(s=4,a=3,b=2,c=1,d=0). Slug parsing mirrors esports_model/src/build_bo3_join.py.
Runs after bo3_download in run_bo3_download.bat. Output:
cowork_snapshot/gamedata/bo3/tier_index.parquet
"""
import json, re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BO3 = ROOT / "cowork_snapshot" / "gamedata" / "bo3"
TIER_ORD = {"s": 4, "a": 3, "b": 2, "c": 1, "d": 0}
SLUG = re.compile(r"^(.+)-vs-(.+)-(\d{2})-(\d{2})-(\d{4})$")


def norm(s):
    if not isinstance(s, str): return ""
    s = s.lower()
    s = re.sub(r"\b(esports|esport|e sports|gaming|team|clan|club|gg)\b", " ", s)
    return re.sub(r"[^a-z0-9]", "", s)


rows = []
with (BO3 / "matches.jsonl").open(encoding="utf-8") as fh:
    for line in fh:
        try:
            m = json.loads(line)
        except Exception:
            continue
        tier = (m.get("tier") or "").lower()
        if tier not in TIER_ORD:
            continue
        mm = SLUG.match(m.get("slug") or "")
        if not mm:
            continue  # hashed/TBD slugs can't be name-joined
        a, b, dd, mo, yy = mm.groups()
        na, nb = norm(a.replace("-", " ")), norm(b.replace("-", " "))
        if not na or not nb:
            continue
        rows.append({"a": min(na, nb), "b": max(na, nb),
                     "date": f"{yy}-{mo}-{dd}", "tier_ord": TIER_ORD[tier]})

df = pd.DataFrame(rows).drop_duplicates(["a", "b", "date"], keep="last")
df.to_parquet(BO3 / "tier_index.parquet", index=False)
print(f"[tier-index] {len(df):,} (pair,date)->tier rows "
      f"({(df.tier_ord >= 4).sum()} tier-S) -> tier_index.parquet")
