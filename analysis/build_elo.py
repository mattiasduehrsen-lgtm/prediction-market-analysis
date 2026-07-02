"""Build CS2 team Elo ratings from PandaScore match history and measure how
well Elo alone predicts match outcomes (the first feasibility gate).

If Elo can't predict CS2 outcomes meaningfully better than a coin flip /
favourite heuristic, no market-beating strategy is coming from this data.

Outputs:
  cs2_elo_history.parquet  — per-match pre-match elo + predicted prob + outcome
  prints accuracy / Brier / log-loss / calibration on a held-out recent window
"""
from __future__ import annotations
import math, sys
from pathlib import Path
from collections import defaultdict
import pandas as pd

GAME = (sys.argv[1] if len(sys.argv) > 1 else "cs2").lower()
GAMES_OK = ("cs2", "lol", "dota2", "valorant", "rl", "ow", "codmw", "r6siege")
if GAME not in GAMES_OK:
    raise SystemExit(f"unknown game {GAME!r}; use one of {GAMES_OK}")

ROOT = Path(__file__).resolve().parents[1]
GD = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"

K = 32.0
BASE = 1500.0
MIN_GAMES = 10   # only score predictions once both teams have this many prior matches

def main():
    df = pd.read_parquet(GD / f"{GAME}_matches.parquet").sort_values("begin_at").reset_index(drop=True)
    elo = defaultdict(lambda: BASE)
    games = defaultdict(int)
    out = []
    for r in df.itertuples(index=False):
        a, b = r.teamA_id, r.teamB_id
        ea, eb = elo[a], elo[b]
        pA = 1.0 / (1.0 + 10 ** ((eb - ea) / 400.0))
        actualA = 1 if r.winner_id == a else 0
        out.append({
            "match_id": r.match_id, "begin_at": r.begin_at,
            "teamA_id": a, "teamB_id": b,
            "teamA_name": r.teamA_name, "teamB_name": r.teamB_name,
            "eloA": ea, "eloB": eb, "pred_pA": pA,
            "gamesA": games[a], "gamesB": games[b],
            "actualA": actualA,
        })
        # update
        elo[a] = ea + K * (actualA - pA)
        elo[b] = eb + K * ((1 - actualA) - (1 - pA))
        games[a] += 1; games[b] += 1
    hist = pd.DataFrame(out)
    hist.to_parquet(GD / f"{GAME}_elo_history.parquet")
    # also dump final ratings
    fin = pd.DataFrame([{"team_id": k, "elo": v, "games": games[k]} for k, v in elo.items()])
    fin.sort_values("elo", ascending=False).to_parquet(GD / f"{GAME}_elo_final.parquet")

    # ── Evaluate on matches where both teams have >= MIN_GAMES history ───────
    ev = hist[(hist["gamesA"] >= MIN_GAMES) & (hist["gamesB"] >= MIN_GAMES)].copy()
    # focus on the window that overlaps Polymarket markets (2025-06+)
    recent = ev[ev["begin_at"] >= "2025-06-01"]
    for label, d in [("all-history (>=%d games)" % MIN_GAMES, ev),
                     ("2025-06+ (market era)", recent)]:
        if not len(d):
            print(f"\n[{label}] no rows"); continue
        pred = d["pred_pA"].clip(1e-6, 1-1e-6)
        act = d["actualA"]
        acc = ((pred > 0.5).astype(int) == act).mean()
        brier = ((pred - act) ** 2).mean()
        ll = -(act * pred.apply(math.log) + (1-act) * (1-pred).apply(math.log)).mean()
        # favourite baseline: always pick higher Elo (== pred>0.5) is same as acc.
        # coin flip baseline brier = 0.25, logloss = 0.693
        print(f"\n[{label}]  n={len(d)}")
        print(f"   accuracy : {acc*100:.1f}%   (coin flip 50%)")
        print(f"   Brier    : {brier:.4f}   (coin flip 0.2500; lower=better)")
        print(f"   log-loss : {ll:.4f}   (coin flip 0.6931; lower=better)")
        # calibration
        print("   calibration (pred bucket -> actual win rate):")
        d2 = d.assign(bucket=(pred*10).astype(int).clip(0,9))
        for bk, g in d2.groupby("bucket"):
            lo = bk/10; print(f"     {lo:.1f}-{lo+0.1:.1f}: pred~{g['pred_pA'].mean():.2f} "
                               f"actual {g['actualA'].mean():.2f}  n={len(g)}")

if __name__ == "__main__":
    main()
