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


def _emit(m, rows):
    tier = (m.get("tier") or "").lower()
    if tier not in TIER_ORD:
        return
    mm = SLUG.match(m.get("slug") or "")
    if not mm:
        return  # hashed/TBD slugs can't be name-joined (teams not final yet)
    a, b, dd, mo, yy = mm.groups()
    na, nb = norm(a.replace("-", " ")), norm(b.replace("-", " "))
    if not na or not nb:
        return
    rows.append({"a": min(na, nb), "b": max(na, nb),
                 "date": f"{yy}-{mo}-{dd}", "tier_ord": TIER_ORD[tier]})


rows = []
# 1) Historical dump. NOTE: the dump dedups by id and NEVER refreshes a row, so
#    upcoming matches are stale/absent in it — hence step 2.
with (BO3 / "matches.jsonl").open(encoding="utf-8") as fh:
    for line in fh:
        try:
            m = json.loads(line)
        except Exception:
            continue
        _emit(m, rows)

# 2) LIVE fetch of the ~500 newest matches (sorted -start_date = ALL upcoming +
#    this week). These are CURRENT rows (real slugs/tiers), appended last so
#    drop_duplicates(keep="last") lets them override stale dump versions.
try:
    import requests
    S = requests.Session()
    S.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    n_live = 0
    for off in (0, 100, 200, 300, 400):
        r = S.get("https://api.bo3.gg/api/v1/matches",
                  params={"sort": "-start_date", "page[limit]": 100, "page[offset]": off},
                  timeout=20)
        got = r.json().get("results", []) if r.status_code == 200 else []
        for m in got:
            _emit(m, rows); n_live += 1
        if len(got) < 100:
            break
    print(f"[tier-index] live fetch: {n_live} newest matches merged")
except Exception as e:
    print(f"[tier-index] live fetch failed ({e}) — index built from dump only")

df = pd.DataFrame(rows).drop_duplicates(["a", "b", "date"], keep="last")
df.to_parquet(BO3 / "tier_index.parquet", index=False)
print(f"[tier-index] {len(df):,} (pair,date)->tier rows "
      f"({(df.tier_ord >= 4).sum()} tier-S) -> tier_index.parquet")
