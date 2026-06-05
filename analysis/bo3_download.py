"""Download bo3.gg's free CS history for the per-map model:
  - matches (teams, winner, maps_score, tier, date)
  - games   (per-map: map_name, number, match_id, winner/round scores)
  - teams   (id -> name)
Saved as resumable jsonl. Filters to start dates >= CUTOFF.
Free public API (api.bo3.gg) — no key, no Cloudflare. Be polite.
"""
from __future__ import annotations
import json, time
from pathlib import Path
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cowork_snapshot" / "gamedata" / "bo3"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://api.bo3.gg/api/v1"
CUTOFF = "2023-01-01"            # 2.5yr warmup before the 2025-06+ Polymarket markets
LIMIT = 250
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120 Safari/537.36", "Accept": "application/json"})


def get(path, params, tries=4):
    for i in range(tries):
        try:
            r = S.get(f"{BASE}/{path}", params=params, timeout=30)
        except Exception as e:
            print(f"    req err {e}; retry"); time.sleep(3); continue
        if r.status_code == 200:
            time.sleep(0.4)
            return r.json()
        if r.status_code == 429:
            print("    429 — sleep 30s"); time.sleep(30); continue
        print(f"    [{r.status_code}] {path} {params}"); time.sleep(2)
    return None


def load_seen(p):
    seen = set()
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                try: seen.add(json.loads(line)["id"])
                except Exception: pass
    return seen


def paginate_until(path, date_field, fname, sort):
    """Paginate sorted-desc by date, append new rows, stop when older than CUTOFF."""
    p = OUT / fname
    seen = load_seen(p)
    fh = p.open("a", encoding="utf-8")
    offset = 0; new = 0; done = False
    while not done:
        data = get(path, {"sort": sort, "page[limit]": LIMIT, "page[offset]": offset})
        rows = (data or {}).get("results") or []
        if not rows:
            break
        for row in rows:
            d = (row.get(date_field) or "")[:10]
            if d and d < CUTOFF:
                done = True; continue
            if row.get("id") in seen:
                continue
            seen.add(row["id"]); fh.write(json.dumps(row) + "\n"); new += 1
        fh.flush()
        offset += LIMIT
        if offset % 2500 == 0:
            print(f"  {path}: offset={offset}, +{new} new, last date={rows[-1].get(date_field,'')[:10]}")
    fh.close()
    print(f"[bo3] {path}: {new} new rows (total seen {len(seen)})")


def download_teams():
    p = OUT / "teams.jsonl"
    seen = load_seen(p)
    fh = p.open("a", encoding="utf-8")
    offset = 0; new = 0
    while True:
        data = get("teams", {"page[limit]": LIMIT, "page[offset]": offset})
        rows = (data or {}).get("results") or []
        if not rows: break
        for row in rows:
            if row.get("id") in seen: continue
            seen.add(row["id"]); fh.write(json.dumps(row) + "\n"); new += 1
        fh.flush(); offset += LIMIT
    fh.close()
    print(f"[bo3] teams: {new} new (total {len(seen)})")


if __name__ == "__main__":
    print(f"=== bo3 download (>= {CUTOFF}) ===")
    download_teams()
    paginate_until("matches", "start_date", "matches.jsonl", "-start_date")
    paginate_until("games", "begin_at", "games.jsonl", "-begin_at")
    print("ALL DONE")
