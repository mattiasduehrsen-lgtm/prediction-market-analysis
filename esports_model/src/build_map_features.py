"""
CS2 map-level Elo -> pre-series features, keyed by PandaScore match_id.

Rebuilds per-(team, map) Elo walk-forward from cs2_map_elo_history.parquet
(bo3-keyed map results; internally consistent team names). BEFORE each series'
first map, emits series-level aggregates over the active map pool:

  - mapelo_veto_prob : Bo3 veto-sim series win prob for A
      (sort per-map probs desc; bans remove extremes; played maps ~ middle
       three; P(win >=2 of 3), independence approx)
  - mapelo_mean_diff : mean rating diff across the active pool
  - mapelo_best_diff / mapelo_worst_diff : A's best / worst map edge
  - mapelo_spread    : std of per-map probs (specialist-vs-generalist signal)
  - mapelo_ngames    : min(total rated map-games of A, B) -- reliability

Rating(team, map) = overall(team) + blended map offset, w = n/(n+5).
All features computed strictly pre-match (updates after emit).
Joined to PS by normalized team-name pair + date (+/-1d) with A/B flip fix.

Output: artifacts/cs2_map_feats.parquet  (match_id = PandaScore id)
"""
import re
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq

_REPO = Path(__file__).resolve().parents[2]
SNAP = _REPO / "cowork_snapshot" / "gamedata"
OUT = _REPO / "esports_model" / "artifacts"

BASE, K_OV, K_MAP, POOL_DAYS = 1500.0, 24.0, 20.0, 120


def elo_p(ra, rb):
    return 1.0 / (1.0 + 10 ** (-(ra - rb) / 400.0))


def series_p_bo3(probs):
    p1, p2, p3 = probs
    return p1 * p2 + p1 * (1 - p2) * p3 + (1 - p1) * p2 * p3


def norm(s):
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = re.sub(r"\b(esports|esport|gaming|team|club|gg|e-sports)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def main():
    h = pq.read_table(SNAP / "cs2_map_elo_history.parquet").to_pandas()
    h["begin_at"] = pd.to_datetime(h.begin_at, utc=True)
    h = h.sort_values(["begin_at", "match_id", "number"]).reset_index(drop=True)

    ov, mp, nmap, ntot = {}, {}, {}, {}
    pool_seen = []
    cur_pool = set()
    last_prune = None

    def rating(t, m):
        n = nmap.get((t, m), 0)
        return ov.get(t, BASE) + (n / (n + 5.0)) * mp.get((t, m), 0.0)

    feats = {}
    for mid, grp in h.groupby("match_id", sort=False):
        g0 = grp.iloc[0]
        a, b, t = g0.teamA, g0.teamB, g0.begin_at
        if last_prune is None or (t - last_prune).days >= 7:
            cutoff = t - pd.Timedelta(days=POOL_DAYS)
            pool_seen[:] = [(tt, m) for tt, m in pool_seen if tt >= cutoff]
            cur_pool = {m for _, m in pool_seen}
            last_prune = t
        if len(cur_pool) >= 3:
            pool = sorted(cur_pool)
            probs = sorted((elo_p(rating(a, m), rating(b, m)) for m in pool), reverse=True)
            diffs = [rating(a, m) - rating(b, m) for m in pool]
            k = len(probs)
            if k >= 7:
                mid3 = probs[2:5]
            elif k >= 5:
                s0 = (k - 3) // 2
                mid3 = probs[s0:s0 + 3]
            else:
                mid3 = probs[:3]
            feats[mid] = {
                "mapelo_veto_prob": series_p_bo3(mid3),
                "mapelo_mean_diff": float(np.mean(diffs)),
                "mapelo_best_diff": float(np.max(diffs)),
                "mapelo_worst_diff": float(np.min(diffs)),
                "mapelo_spread": float(np.std(probs)),
                "mapelo_ngames": float(min(ntot.get(a, 0), ntot.get(b, 0))),
            }
        for r in grp.itertuples(index=False):
            m, res = r.map, float(r.actualA)
            pa = elo_p(rating(a, m), rating(b, m))
            oa, ob = ov.get(a, BASE), ov.get(b, BASE)
            p_ov = elo_p(oa, ob)
            ov[a] = oa + K_OV * (res - p_ov)
            ov[b] = ob + K_OV * ((1 - res) - (1 - p_ov))
            mp[(a, m)] = mp.get((a, m), 0.0) + K_MAP * (res - pa)
            mp[(b, m)] = mp.get((b, m), 0.0) + K_MAP * ((1 - res) - (1 - pa))
            nmap[(a, m)] = nmap.get((a, m), 0) + 1
            nmap[(b, m)] = nmap.get((b, m), 0) + 1
            ntot[a] = ntot.get(a, 0) + 1
            ntot[b] = ntot.get(b, 0) + 1
            pool_seen.append((r.begin_at, m))

    f = pd.DataFrame.from_dict(feats, orient="index").rename_axis("hid").reset_index()
    hm = h.drop_duplicates("match_id")[["match_id", "teamA", "teamB", "begin_at"]]
    hm = hm.merge(f, left_on="match_id", right_on="hid")
    hm["pair"] = [tuple(sorted((norm(a), norm(b)))) for a, b in zip(hm.teamA, hm.teamB)]
    hm["date"] = hm.begin_at.dt.date
    hm["nA"] = hm.teamA.map(norm)

    ps = pq.read_table(SNAP / "pandascore" / "cs2_matches.parquet").to_pandas()
    ps["begin_at"] = pd.to_datetime(ps.begin_at, utc=True)
    ps = ps.sort_values("begin_at")
    ps["pair"] = [tuple(sorted((norm(a), norm(b)))) for a, b in zip(ps.teamA_name, ps.teamB_name)]
    ps["nA"] = ps.teamA_name.map(norm)
    ps["date"] = ps.begin_at.dt.date

    idx = {}
    for r in hm.itertuples(index=False):
        idx.setdefault(r.pair, []).append(r)
    one = pd.Timedelta(days=1).to_pytimedelta()
    used, rows = set(), []
    for r in ps.itertuples(index=False):
        hit = None
        for d in (r.date, r.date - one, r.date + one):
            for x in idx.get(r.pair, []):
                if x.date == d and x.hid not in used:
                    hit = x
                    break
            if hit:
                break
        if hit is None:
            continue
        used.add(hit.hid)
        flip = hit.nA != r.nA
        rows.append({
            "match_id": r.match_id,
            "mapelo_veto_prob": 1 - hit.mapelo_veto_prob if flip else hit.mapelo_veto_prob,
            "mapelo_mean_diff": -hit.mapelo_mean_diff if flip else hit.mapelo_mean_diff,
            "mapelo_best_diff": -hit.mapelo_worst_diff if flip else hit.mapelo_best_diff,
            "mapelo_worst_diff": -hit.mapelo_best_diff if flip else hit.mapelo_worst_diff,
            "mapelo_spread": hit.mapelo_spread,
            "mapelo_ngames": hit.mapelo_ngames,
        })
    out = pd.DataFrame(rows)
    out.to_parquet(OUT / "cs2_map_feats.parquet", index=False)
    print(f"map features: {len(f):,} history matches -> {len(out):,} PS matches joined")


if __name__ == "__main__":
    main()
