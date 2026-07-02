"""Flatten <game>_matches_raw.jsonl -> <game>_matches.parquet (finished 2-team
matches). Also flatten teams. Game-parameterized: `flatten.py [cs2|lol]` (default
cs2). Safe to run on partial download; re-run as data grows.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import pandas as pd

GAME = (sys.argv[1] if len(sys.argv) > 1 else "cs2").lower()
GAMES_OK = ("cs2", "lol", "dota2", "valorant", "rl", "ow", "codmw", "r6siege")
if GAME not in GAMES_OK:
    raise SystemExit(f"unknown game {GAME!r}; use one of {GAMES_OK}")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
RAW = OUT / f"{GAME}_matches_raw.jsonl"
TEAMS = OUT / f"{GAME}_teams_raw.jsonl"

def flatten_matches():
    rows = []
    with RAW.open(encoding="utf-8") as fh:
        for line in fh:
            try: m = json.loads(line)
            except Exception: continue
            if m.get("status") != "finished":
                continue
            opps = m.get("opponents") or []
            if len(opps) != 2:
                continue
            a = (opps[0] or {}).get("opponent") or {}
            b = (opps[1] or {}).get("opponent") or {}
            if not a.get("id") or not b.get("id"):
                continue
            results = {r.get("team_id"): r.get("score") for r in (m.get("results") or [])}
            rows.append({
                "match_id": m.get("id"),
                "begin_at": m.get("begin_at"),
                "end_at": m.get("end_at"),
                "teamA_id": a.get("id"), "teamA_name": a.get("name"), "teamA_acr": a.get("acronym"),
                "teamB_id": b.get("id"), "teamB_name": b.get("name"), "teamB_acr": b.get("acronym"),
                "winner_id": m.get("winner_id"),
                "scoreA": results.get(a.get("id")), "scoreB": results.get(b.get("id")),
                "num_games": m.get("number_of_games"),
                "league": (m.get("league") or {}).get("name"),
                "serie": (m.get("serie") or {}).get("full_name"),
                "tournament": (m.get("tournament") or {}).get("name"),
                "match_type": m.get("match_type"),
            })
    df = pd.DataFrame(rows)
    if len(df):
        df["begin_at"] = pd.to_datetime(df["begin_at"], errors="coerce", utc=True)
        df = df.dropna(subset=["begin_at", "winner_id"]).sort_values("begin_at").reset_index(drop=True)
        df.to_parquet(OUT / f"{GAME}_matches.parquet")
    print(f"[flatten] matches: {len(df)} finished 2-team with winner")
    if len(df):
        print(f"   date range: {df['begin_at'].min()} .. {df['begin_at'].max()}")
        print(f"   unique teams: {len(set(df['teamA_id']) | set(df['teamB_id']))}")
    return df

def flatten_teams():
    if not TEAMS.exists():
        print("[flatten] no teams file yet"); return
    rows = []
    with TEAMS.open(encoding="utf-8") as fh:
        for line in fh:
            try: t = json.loads(line)
            except Exception: continue
            rows.append({"id": t.get("id"), "name": t.get("name"),
                         "acronym": t.get("acronym"), "slug": t.get("slug"),
                         "location": t.get("location")})
    df = pd.DataFrame(rows).drop_duplicates("id")
    df.to_parquet(OUT / f"{GAME}_teams.parquet")
    print(f"[flatten] teams: {len(df)}")

if __name__ == "__main__":
    flatten_teams()
    flatten_matches()
