"""Per-map CS2 model from bo3 games. Walk-forward map-adjusted Elo.

For each team we track:
  - overall_elo  (all maps)            -> base team strength
  - map_elo[(team,map)]                -> strength on that specific map
  - map_games[(team,map)]              -> sample size for shrinkage

Prediction for A vs B on map M (effective rating blends map + overall by sample):
  eff(T,M) = overall[T] + shrink * (map_elo[T,M] - overall[T])
  shrink   = map_games[T,M] / (map_games[T,M] + C)
  P(A wins M) = 1 / (1 + 10**((eff_B - eff_A)/400))

THE GATE: compare map-AWARE vs map-AGNOSTIC (overall-only) Brier/log-loss.
If map-aware doesn't beat map-agnostic, knowing the map adds nothing.

Outputs cs2_map_elo_history.parquet (per-game pre-match preds + outcome + map).
"""
from __future__ import annotations
import json, math
from pathlib import Path
from collections import defaultdict
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BO3 = ROOT / "cowork_snapshot" / "gamedata" / "bo3"
OUT = ROOT / "cowork_snapshot" / "gamedata"

BASE = 1500.0
K_OVERALL = 24.0
K_MAP = 24.0
C_SHRINK = 10.0      # games-on-map for the map signal to be half-trusted
MIN_GAMES = 15       # eval only when both teams have this many total games

def logistic(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))

def main():
    gp = BO3 / "games.jsonl"
    games = []
    for line in gp.open(encoding="utf-8"):
        try: g = json.loads(line)
        except Exception: continue
        if g.get("game_version") != 2:          # CS2 only
            continue
        w, l, mp = g.get("winner_clan_name"), g.get("loser_clan_name"), g.get("map_name")
        bt = g.get("begin_at")
        if not (w and l and mp and bt) or w == l:
            continue
        games.append((bt, w.strip(), l.strip(), mp))
    games.sort(key=lambda x: x[0])
    print(f"usable CS2 games: {len(games)}")

    overall = defaultdict(lambda: BASE)
    map_elo = defaultdict(lambda: None)        # (team,map) -> elo (lazy init)
    map_games = defaultdict(int)
    tot_games = defaultdict(int)

    def eff(team, mp):
        me = map_elo[(team, mp)]
        ov = overall[team]
        if me is None:
            return ov
        n = map_games[(team, mp)]
        shrink = n / (n + C_SHRINK)
        return ov + shrink * (me - ov)

    rows = []
    for bt, win, lose, mp in games:
        # order teams independent of outcome to avoid label leakage
        A, B = sorted((win, lose))
        actualA = 1 if A == win else 0
        # map-aware
        effA, effB = eff(A, mp), eff(B, mp)
        p_map = logistic(effA, effB)
        # map-agnostic baseline
        p_ov = logistic(overall[A], overall[B])
        rows.append({
            "begin_at": bt, "teamA": A, "teamB": B, "map": mp,
            "p_map": p_map, "p_overall": p_ov, "actualA": actualA,
            "gA": tot_games[A], "gB": tot_games[B],
            "mgA": map_games[(A, mp)], "mgB": map_games[(B, mp)],
        })
        # --- updates (winner/loser) ---
        # overall
        pW = logistic(overall[win], overall[lose])
        overall[win] += K_OVERALL * (1 - pW)
        overall[lose] += K_OVERALL * (0 - (1 - pW))
        # map (init lazily to current overall so deviation starts at 0)
        for t in (win, lose):
            if map_elo[(t, mp)] is None:
                map_elo[(t, mp)] = overall[t]
        pWm = logistic(map_elo[(win, mp)], map_elo[(lose, mp)])
        map_elo[(win, mp)] += K_MAP * (1 - pWm)
        map_elo[(lose, mp)] += K_MAP * (0 - (1 - pWm))
        map_games[(win, mp)] += 1; map_games[(lose, mp)] += 1
        tot_games[win] += 1; tot_games[lose] += 1

    hist = pd.DataFrame(rows)
    hist.to_parquet(OUT / "cs2_map_elo_history.parquet")
    # final ratings for live use
    fin = []
    for (t, mp), me in map_elo.items():
        if me is not None:
            fin.append({"team": t, "map": mp, "map_elo": me,
                        "map_games": map_games[(t, mp)], "overall_elo": overall[t]})
    pd.DataFrame(fin).to_parquet(OUT / "cs2_map_elo_final.parquet")

    # ---- THE GATE: map-aware vs map-agnostic ----
    ev = hist[(hist["gA"] >= MIN_GAMES) & (hist["gB"] >= MIN_GAMES)].copy()
    def metrics(p, a):
        p = p.clip(1e-6, 1 - 1e-6)
        acc = ((p > 0.5).astype(int) == a).mean()
        brier = ((p - a) ** 2).mean()
        ll = -(a * p.apply(math.log) + (1 - a) * (1 - p).apply(math.log)).mean()
        return acc, brier, ll
    for label, d in [("all eval games", ev),
                     ("both teams >=8 games on the map", ev[(ev.mgA >= 8) & (ev.mgB >= 8)])]:
        if not len(d):
            print(f"\n[{label}] no rows"); continue
        a = d["actualA"]
        am = metrics(d["p_map"], a); ag = metrics(d["p_overall"], a)
        print(f"\n[{label}]  n={len(d)}")
        print(f"  map-AWARE   : acc {am[0]*100:5.1f}%  Brier {am[1]:.4f}  logloss {am[2]:.4f}")
        print(f"  map-AGNOSTIC: acc {ag[0]*100:5.1f}%  Brier {ag[1]:.4f}  logloss {ag[2]:.4f}")
        d_brier = ag[1] - am[1]
        print(f"  --> map info {'HELPS' if d_brier>0 else 'does NOT help'} "
              f"(Brier {'-' if d_brier>0 else '+'}{abs(d_brier):.4f})")

if __name__ == "__main__":
    main()
