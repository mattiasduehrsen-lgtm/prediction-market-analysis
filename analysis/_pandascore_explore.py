"""Explore what the PandaScore free tier gives us for CS2.
Tests auth, coverage, historical depth, odds availability, rate limits.
Reads PANDASCORE_TOKEN from .env. Prints findings; downloads nothing yet.
"""
from __future__ import annotations
import os, json, time
from pathlib import Path
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
TOKEN = os.environ.get("PANDASCORE_TOKEN", "").strip()
print("token present:", bool(TOKEN))
S = requests.Session()
S.headers.update({"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
BASE = "https://api.pandascore.co"

def call(path, params=None, label=None):
    params = params or {}
    try:
        r = S.get(BASE + path, params=params, timeout=20)
    except Exception as e:
        print(f"  [ERR] {label or path}: {e}"); return None, None
    rl = {k: v for k, v in r.headers.items() if k.lower().startswith("x-rate")}
    print(f"  [{r.status_code}] {label or path}  ratelimit={rl}")
    if r.status_code != 200:
        print(f"        body: {str(r.text)[:160]}")
        return None, r
    try:
        data = r.json()
    except Exception:
        return None, r
    return data, r

print("\n=== 1. CS2 videogame endpoints (csgo namespace) ===")
# Past matches (finished, with results)
past, _ = call("/csgo/matches/past", {"per_page": 3, "sort": "-end_at"}, "csgo/matches/past")
if past:
    print(f"        got {len(past)} matches; sample:")
    m = past[0]
    print(f"        keys: {sorted(m.keys())}")
    opps = [o.get('opponent',{}).get('name') for o in (m.get('opponents') or [])]
    print(f"        {m.get('name')} | {m.get('begin_at')} | opponents={opps}")
    print(f"        winner_id={ (m.get('winner') or {}).get('id') } status={m.get('status')}")
    print(f"        league={ (m.get('league') or {}).get('name') } serie={ (m.get('serie') or {}).get('full_name') }")
    print(f"        number_of_games={m.get('number_of_games')} results={m.get('results')}")

print("\n=== 2. Historical depth — how far back can we page? ===")
old, _ = call("/csgo/matches/past",
              {"per_page": 1, "sort": "end_at", "page": 1}, "oldest match (sort asc)")
if old:
    print(f"        oldest available: {old[0].get('begin_at')} - {old[0].get('name')}")

print("\n=== 3. Teams ===")
teams, _ = call("/csgo/teams", {"per_page": 2}, "csgo/teams")
if teams:
    print(f"        team keys: {sorted(teams[0].keys())}")
    print(f"        sample: {teams[0].get('name')} id={teams[0].get('id')}")

print("\n=== 4. ODDS availability (the key question) ===")
# Odds endpoints — try match odds
odds, r = call("/csgo/matches/upcoming", {"per_page": 1}, "upcoming match (for odds id)")
if odds:
    mid = odds[0].get("id")
    print(f"        testing odds for upcoming match id={mid}")
    od, _ = call(f"/matches/{mid}/odds", None, f"/matches/{mid}/odds")
    if od is not None:
        print(f"        ODDS RESPONSE: {json.dumps(od)[:300]}")
# Generic odds endpoint
call("/odds", {"per_page": 1}, "/odds (generic)")

print("\n=== 5. Per-game / map detail (for modeling) ===")
if past:
    mid = past[0].get("id")
    games, _ = call(f"/csgo/matches/{mid}/games", None, "match games (maps)")
    if games:
        print(f"        {len(games)} games; sample keys: {sorted(games[0].keys()) if games else None}")

print("\nDONE. Summary of what we can build will be derived from above.")
