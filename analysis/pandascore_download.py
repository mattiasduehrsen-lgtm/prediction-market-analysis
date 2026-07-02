"""Download esports match history + teams from PandaScore (free tier) to laptop.

Game-parameterized: `python pandascore_download.py [cs2|lol]` (default cs2).
  cs2 -> /csgo/matches/past + /csgo/teams -> cs2_matches_raw.jsonl
  lol -> /lol/matches/past  + /lol/teams  -> lol_matches_raw.jsonl

Resumable: appends raw match objects to <game>_matches_raw.jsonl, dedups by id.
Respects the 1000 req/hour rate limit (watches X-Rate-Limit-Remaining).
Chunks by month to stay under PandaScore's pagination cap (page*per_page<=10000).

Run:  .venv\\Scripts\\python.exe analysis\\pandascore_download.py lol
Safe to re-run / interrupt.
"""
from __future__ import annotations
import os, sys, json, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests
from dotenv import load_dotenv

GAME = (sys.argv[1] if len(sys.argv) > 1 else "cs2").lower()
# (matches endpoint, teams endpoint, file prefix)
GAME_CFG = {
    "cs2":      ("/csgo/matches/past",     "/csgo/teams",     "cs2"),
    "lol":      ("/lol/matches/past",      "/lol/teams",      "lol"),
    # v1.55 net-widening: every esport PandaScore covers that Polymarket/GRID could
    # list. Data first, models next, wiring when the markets appear.
    "dota2":    ("/dota2/matches/past",    "/dota2/teams",    "dota2"),
    "valorant": ("/valorant/matches/past", "/valorant/teams", "valorant"),
    "rl":       ("/rl/matches/past",       "/rl/teams",       "rl"),
    "ow":       ("/ow/matches/past",       "/ow/teams",       "ow"),
    "codmw":    ("/codmw/matches/past",    "/codmw/teams",    "codmw"),
    "r6siege":  ("/r6siege/matches/past",  "/r6siege/teams",  "r6siege"),
}
if GAME not in GAME_CFG:
    raise SystemExit(f"unknown game {GAME!r}; use one of {list(GAME_CFG)}")
MATCH_EP, TEAMS_EP, PREFIX = GAME_CFG[GAME]

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TOKEN = os.environ["PANDASCORE_TOKEN"].strip()
OUT = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
OUT.mkdir(parents=True, exist_ok=True)
RAW = OUT / f"{PREFIX}_matches_raw.jsonl"
TEAMS = OUT / f"{PREFIX}_teams_raw.jsonl"

S = requests.Session()
S.headers.update({"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
BASE = "https://api.pandascore.co"

START = datetime(2022, 6, 1, tzinfo=timezone.utc)   # Elo warmup + late CSGO + all CS2
PER_PAGE = 100

def _sleep_for_rate(resp):
    """Stay comfortably under 1000/hr. If remaining is low, wait."""
    try:
        rem = int(resp.headers.get("X-Rate-Limit-Remaining", "999"))
    except Exception:
        rem = 999
    if rem <= 5:
        print(f"    rate limit low ({rem}) — sleeping 60s")
        time.sleep(60)
    else:
        time.sleep(1.2)   # ~830/hr worst case, safe

def get(path, params, tries=4):
    for i in range(tries):
        try:
            r = S.get(BASE + path, params=params, timeout=30)
        except Exception as e:
            print(f"    req error {e}; retry"); time.sleep(3); continue
        if r.status_code == 200:
            _sleep_for_rate(r)
            return r.json()
        if r.status_code == 429:
            print("    429 rate limited — sleeping 90s"); time.sleep(90); continue
        print(f"    [{r.status_code}] {path} {params} -> {str(r.text)[:120]}")
        time.sleep(2)
    return None

def load_seen():
    """Returns (seen_ids, newest_begin_at_or_None). One pass; begin_at is parsed
    from the same json we already decode for the id, so this costs nothing extra
    and lets incremental runs resume from the data itself (no state file to drift)."""
    seen, max_dt = set(), None
    if RAW.exists():
        with RAW.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    m = json.loads(line)
                    seen.add(m["id"])
                    b = m.get("begin_at")
                    if b and (max_dt is None or b > max_dt):
                        max_dt = b
                except Exception:
                    pass
    return seen, max_dt

def month_ranges(start: datetime, end: datetime):
    cur = start
    while cur < end:
        if cur.month == 12:
            nxt = cur.replace(year=cur.year+1, month=1)
        else:
            nxt = cur.replace(month=cur.month+1)
        yield cur, min(nxt, end)
        cur = nxt

def download_matches(full: bool = False):
    seen, max_dt = load_seen()
    now = datetime.now(timezone.utc)
    # TOKEN-BUDGET FIX (2026-07-01): incremental by default. The old behaviour
    # re-walked EVERY month since 2022 on EVERY run (~250-600 requests per game,
    # 99% re-fetching already-saved data) — with 8 games on schedules that would
    # collide with the 1,000 req/hr free-tier cap and starve the live refreshes.
    # Now: resume from (newest saved match - 7d overlap) -> ~2-5 requests/run.
    # First run for a game (no file) or explicit `full` arg = full backfill.
    start = START
    if not full and max_dt:
        try:
            resume = datetime.fromisoformat(max_dt.replace("Z", "+00:00")) - timedelta(days=7)
            start = max(START, resume)
        except Exception:
            pass
    mode = "FULL backfill" if start == START else f"incremental since {start.date()}"
    print(f"[pandascore] resume: {len(seen)} matches saved; mode={mode}")
    fh = RAW.open("a", encoding="utf-8")
    total_new = 0
    for mstart, mend in month_ranges(start, now):
        rng = f"{mstart.strftime('%Y-%m-%dT%H:%M:%SZ')},{mend.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        page = 1
        month_new = 0
        while True:
            data = get(MATCH_EP, {
                "range[begin_at]": rng, "per_page": PER_PAGE, "page": page,
                "sort": "begin_at",
            })
            if not data:
                break
            for m in data:
                if m.get("id") in seen:
                    continue
                seen.add(m["id"])
                fh.write(json.dumps(m) + "\n")
                month_new += 1; total_new += 1
            fh.flush()
            if len(data) < PER_PAGE:
                break
            page += 1
        print(f"  {mstart.date()} .. {mend.date()}: +{month_new} new (total_new={total_new})")
    fh.close()
    print(f"[pandascore] matches done. total_new={total_new}, grand_total={len(seen)}")

def download_teams(full: bool = False):
    seen = set()
    if TEAMS.exists():
        with TEAMS.open(encoding="utf-8") as f:
            for line in f:
                try: seen.add(json.loads(line)["id"])
                except Exception: pass
    fh = TEAMS.open("a", encoding="utf-8")
    page = 1; total = 0; stale_pages = 0
    # TOKEN-BUDGET FIX: on incremental runs, sort by -modified_at so new/changed
    # teams come FIRST, and stop after 2 consecutive pages with nothing new
    # (~50 pages -> ~2-3 per run). Full backfill (no file / `full`) walks everything.
    incremental = bool(seen) and not full
    params_extra = {"sort": "-modified_at"} if incremental else {}
    while True:
        data = get(TEAMS_EP, {"per_page": PER_PAGE, "page": page, **params_extra})
        if not data:
            break
        added = 0
        for t in data:
            if t.get("id") in seen: continue
            seen.add(t["id"]); fh.write(json.dumps(t)+"\n"); added += 1; total += 1
        fh.flush()
        if incremental:
            stale_pages = stale_pages + 1 if added == 0 else 0
            if stale_pages >= 2:
                break
        if len(data) < PER_PAGE or page >= 100:  # 10k cap
            break
        page += 1
    fh.close()
    print(f"[pandascore] teams done. total={len(seen)}")

if __name__ == "__main__":
    FULL = "full" in [a.lower() for a in sys.argv[2:]]
    print(f"=== downloading {GAME.upper()} teams ({TEAMS_EP}){' [FULL]' if FULL else ''} ===")
    download_teams(full=FULL)
    print(f"=== downloading {GAME.upper()} match history ({MATCH_EP}){' [FULL]' if FULL else ''} ===")
    download_matches(full=FULL)
    print("ALL DONE")
