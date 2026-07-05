"""Verify EVERY data file Cowork needs is present and READABLE on this PC (catches
truncated/corrupt copies). Run from repo root with the project venv."""
import json, sys
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "cowork_snapshot"

PARQUETS = [
    "gamedata/pandascore/cs2_matches.parquet", "gamedata/pandascore/lol_matches.parquet",
    "gamedata/pandascore/cs2_elo_final.parquet", "gamedata/pandascore/lol_elo_final.parquet",
    "gamedata/pandascore/cs2_elo_history.parquet", "gamedata/pandascore/lol_elo_history.parquet",
    "gamedata/pandascore/cs2_teams.parquet", "gamedata/pandascore/lol_teams.parquet",
    "gamedata/prematch_prices.parquet", "gamedata/cs2_map_elo_final.parquet",
    "gamedata/cs2_map_elo_history.parquet", "gamedata/polymarket_cs2_markets.parquet",
    "esports/clob_esports_markets.parquet", "esports/resolutions.parquet",
    "gamedata/bo3/tier_index.parquet",
]
JSONL = [
    "gamedata/pandascore/cs2_matches_raw.jsonl", "gamedata/pandascore/lol_matches_raw.jsonl",
    "live/fade_events.jsonl", "live/live_orders.jsonl",
    "gamedata/bo3/matches.jsonl",
] + [str(f.relative_to(Path(__file__).resolve().parents[1] / "cowork_snapshot"))
     for f in sorted((Path(__file__).resolve().parents[1] / "cowork_snapshot" / "live" / "price_capture").glob("prices_*.jsonl"))]
CSV = ["live/lol_observations.csv", "live/live_results.csv"]
JSONF = ["live/fade_targets.json", "live/fade_targets_paper.json", "live/live_daily_pnl.json"]

ok = bad = 0
def report(name, status, detail=""):
    global ok, bad
    if status: ok += 1;  print(f"  OK   {name:<52} {detail}")
    else:      bad += 1; print(f"  FAIL {name:<52} {detail}")

print("="*80); print(" PARQUET")
for rel in PARQUETS:
    p = SNAP / rel
    if not p.exists(): report(rel, False, "MISSING"); continue
    try:
        t = pq.read_table(p); report(rel, True, f"{t.num_rows:,} rows x {t.num_columns} cols")
    except Exception as e:
        report(rel, False, f"UNREADABLE: {str(e)[:50]}")

print("="*80); print(" JSONL")
for rel in JSONL:
    p = SNAP / rel
    if not p.exists(): report(rel, False, "MISSING"); continue
    try:
        n = 0; last = None
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line); n += 1
        report(rel, last is not None, f"{n:,} records, last parses OK")
    except Exception as e:
        report(rel, False, f"UNREADABLE: {str(e)[:50]}")

print("="*80); print(" CSV / JSON")
for rel in CSV:
    p = SNAP / rel
    if not p.exists(): report(rel, False, "MISSING"); continue
    try:
        d = pd.read_csv(p); report(rel, True, f"{len(d):,} rows x {len(d.columns)} cols")
    except Exception as e:
        report(rel, False, f"UNREADABLE: {str(e)[:50]}")
for rel in JSONF:
    p = SNAP / rel
    if not p.exists(): report(rel, False, "MISSING"); continue
    try:
        d = json.loads(p.read_text(encoding="utf-8")); report(rel, True, f"keys={list(d)[:4]}")
    except Exception as e:
        report(rel, False, f"UNREADABLE: {str(e)[:50]}")

print("="*80)
print(f" RESULT: {ok} readable, {bad} problems")
if bad: print(" >>> FIX the FAIL/MISSING files before handing to Cowork.")
else:   print(" >>> ALL DATA READABLE — safe to hand to Cowork.")
