"""Run the walk-forward pass and dump FINAL per-team state for the predictor.
Mirrors the rating updates in features.py exactly.

v2: also stores the roster-staleness state the LoL shipped model needs
(recent match timestamps for act90, post-gap counter, Glicko sigma for
time-inflated phi)."""
import math, sys, json
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from features import load_matches, team_region, Glicko, _streak, PS, OUT, GAP_DAYS

BASE = 1500.0; K = 32.0; DK = 40.0; DECAY_HALF = 180.0


def build_state(game):
    df = load_matches(game)
    region = team_region(game)
    elo = {}; delo = {}; last_elo_t = {}; last_played = {}
    hist = {}; games_ct = {}; gl = Glicko()
    h2h = {}
    names = {}
    recent = {}; postgap = {}
    for r in df.itertuples(index=False):
        a, b, t = r.teamA_id, r.teamB_id, r.begin_at
        names[a] = r.teamA_name; names[b] = r.teamB_name
        # post-gap counter uses the idle time BEFORE this match
        for team in (a, b):
            lp = last_played.get(team)
            gap = (t - lp).total_seconds()/86400.0 if lp is not None else 365.0
            if gap >= GAP_DAYS: postgap[team] = 0
            else: postgap[team] = postgap.get(team, 20) + 1
        ea = elo.get(a, BASE); eb = elo.get(b, BASE)
        pa = 1/(1+10**(-(ea-eb)/400))
        elo[a] = ea + K*(r.actualA-pa); elo[b] = eb + K*((1-r.actualA)-(1-pa))
        da = delo.get(a, BASE); db = delo.get(b, BASE)
        for team, val in ((a, da), (b, db)):
            lt = last_elo_t.get(team)
            if lt is not None:
                days = (t-lt).total_seconds()/86400.0
                w = 0.5**(days/DECAY_HALF)
                if team == a: da = BASE+(val-BASE)*w
                else: db = BASE+(val-BASE)*w
        pda = 1/(1+10**(-(da-db)/400))
        margin = abs(r.scoreA-r.scoreB); mult = math.log1p(margin) if margin > 0 else 0.5
        delo[a] = da + DK*mult*(r.actualA-pda); delo[b] = db + DK*mult*((1-r.actualA)-(1-pda))
        last_elo_t[a] = t; last_elo_t[b] = t
        gl.update(a, b, r.actualA)
        hist.setdefault(a, []).append(r.actualA); hist.setdefault(b, []).append(1-r.actualA)
        recent.setdefault(a, []).append(int(t.value)); recent.setdefault(b, []).append(int(t.value))
        last_played[a] = t; last_played[b] = t
        games_ct[a] = games_ct.get(a, 0)+1; games_ct[b] = games_ct.get(b, 0)+1
        key = (min(a, b), max(a, b)); hh = h2h.get(key, [0, 0])
        hh = [hh[0]+(r.actualA if a < b else 1-r.actualA), hh[1]+1]; h2h[key] = hh

    rows = []
    for tid in games_ct:
        gmu, gphi = gl.rating(tid)
        h = hist.get(tid, [])
        rows.append({
            "team_id": tid, "name": names.get(tid, ""),
            "elo": elo[tid], "delo": delo[tid],
            "last_elo_ns": int(last_elo_t[tid].value),
            "glicko_mu": gmu, "glicko_phi": gphi,
            "glicko_sigma": gl.sigma.get(tid, 0.06),
            "form10": float(np.mean(h[-10:])) if h else 0.5,
            "streak": _streak(h), "games": games_ct[tid],
            "last_played_ns": int(last_played[tid].value),
            "location": region.get(tid, "??"),
            "recent30_ns": recent.get(tid, [])[-30:],
            "postgap": min(postgap.get(tid, 20), 20),
        })
    st = pd.DataFrame(rows)
    st.to_parquet(OUT / f"{game}_team_state.parquet", index=False)
    h2h_rows = [{"a": k[0], "b": k[1], "wins_low": v[0], "n": v[1]} for k, v in h2h.items()]
    pd.DataFrame(h2h_rows).to_parquet(OUT / f"{game}_h2h.parquet", index=False)
    meta = {"max_ts_ns": int(df.begin_at.max().value)}
    if game == "lol":
        from features import lol_patch
        pv = list(lol_patch(df.match_id.tolist()).values())
        meta["patch_default"] = float(np.median(pv)) if pv else float("nan")
    (OUT / f"{game}_state_meta.json").write_text(json.dumps(meta))
    print(f"{game}: state for {len(st):,} teams, {len(h2h_rows):,} h2h pairs")


if __name__ == "__main__":
    for g in (sys.argv[1:] or ["cs2", "lol"]):
        build_state(g)
