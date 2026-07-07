"""Bookmaker-odds capture logger — the external truth reference (2026-07-06).

WHY: the GRID re-fit showed the market repriced faster than our models. The open
question is WHO the market is now — if GRID-era Polymarket prices just track
sharp bookmaker lines, the edge ceiling is the book margin and every model-vs-
market claim can be sanity-checked against the books.

bo3.gg's matches API carries a bookmaker's live odds inline (`bet_updates`):
match-winner coefficients + totals/handicap props + an `aggrement_score` that
behaves like a vig-free implied probability. CRITICALLY these are LIVE
snapshots — finished matches collapse to coeff 1.001/inactive, so the closing
line is NOT retroactively recoverable. Hence this logger: poll upcoming/live
CS2 matches every few minutes and archive the odds ourselves, price_capture-
style. In a week we have book closes to join against Polymarket marks
(output/price_capture + output/tape_backfill) and results.

One API call per cycle (odds ride inline on the matches page) — negligible load.

Run: .venv\\Scripts\\python.exe -u odds_capture.py   (via watch_odds_capture.bat)
Output: output/odds_capture/odds_YYYYMMDD.jsonl
"""
from __future__ import annotations
import json, time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output" / "odds_capture"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "https://api.bo3.gg/api/v1"
CYCLE_S = 300              # book lines move slowly pre-match; 5 min is plenty
PAGE_LIMIT = 100
STATUSES = ("current", "upcoming")   # finished = degenerate odds, skip
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120 Safari/537.36",
                  "Accept": "application/json"})


def fetch(status):
    try:
        r = S.get(f"{BASE}/matches", params={
            "filter[matches.status][eq]": status,
            "filter[matches.discipline_id][eq]": 1,   # CS2 (bo3 has no LoL)
            "sort": "start_date", "page[limit]": PAGE_LIMIT}, timeout=30)
        if r.status_code != 200:
            return []
        return r.json().get("results") or []
    except Exception as e:
        print(f"[odds-capture] fetch {status} failed: {e}")
        return []


def rows_for(m, now):
    bu = m.get("bet_updates")
    if not isinstance(bu, dict):
        return []
    t1, t2 = bu.get("team_1") or {}, bu.get("team_2") or {}
    if not t1 and not t2:
        return []
    base = {"ts": round(now, 1), "slug": m.get("slug"), "status": m.get("status"),
            "start_date": m.get("start_date"), "tier": m.get("tier"),
            "tier_rank": m.get("tier_rank"), "bo_type": m.get("bo_type"),
            "provider": bu.get("bet_provider_id")}
    out = [dict(base, kind="winner",
                team_1=t1.get("name"), team_2=t2.get("name"),
                coeff_1=t1.get("coeff"), coeff_2=t2.get("coeff"),
                max_coeff_1=t1.get("max_coeff"), max_coeff_2=t2.get("max_coeff"),
                imp_1=t1.get("aggrement_score"), imp_2=t2.get("aggrement_score"),
                active_1=t1.get("active"), active_2=t2.get("active"))]
    for am in (bu.get("additional_markets") or []):
        out.append(dict(base, kind="prop", bet_type=am.get("bet_type"),
                        team_id=am.get("team_id"), coeff=am.get("coeff"),
                        max_coeff=am.get("max_coeff"),
                        imp=am.get("aggrement_score"), active=am.get("active")))
    return out


def main():
    print(f"[odds-capture] starting; cycle {CYCLE_S}s, statuses {STATUSES}")
    while True:
        t0 = time.time()
        n = 0
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = OUT_DIR / f"odds_{day}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            for st in STATUSES:
                for m in fetch(st):
                    for row in rows_for(m, t0):
                        fh.write(json.dumps(row) + "\n")
                        n += 1
                time.sleep(1.0)
        print(f"[odds-capture] heartbeat: wrote {n} rows in {time.time()-t0:.0f}s")
        time.sleep(max(5.0, CYCLE_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
