"""GRID-era in-play join — enlarge the contrarian evidence base (2026-07-06).

The pre-registered in-play gate (contrarian n>=100, p<0.02) is stuck at n=51
on the live paper stream. This builds the SAME test on the GRID-era population
from independent data: bo3.gg per-map results (map-1 winner + map-2 begin time)
joined against the backfilled Polymarket trade tape (analysis/tape_backfill.py),
pricing the map-1 LOSER at the last tape fill in the between-maps window
[map2_begin - 10min, map2_begin - 30s] — the market knows the map-1 result,
map 2 has not started.

EVIDENCE ONLY: the pre-registered adjudication stays on the live paper stream
(analysis/_inplay_sig.py at n>=100). This is the GRID-era robustness read.

Run: .venv\\Scripts\\python.exe -u analysis/inplay_tape_join.py [fetch|join]
Output: output/tape_backfill/inplay_bo3.parquet + printed report
"""
import json, math, re, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
from tape_backfill import universe, TR, _norm

OUT = ROOT / "output" / "tape_backfill"
BO3_CACHE = OUT / "inplay_bo3.parquet"
BASE = "https://api.bo3.gg/api/v1"
GRID_T0 = pd.Timestamp("2026-06-23", tz="UTC")
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 Chrome/120 Safari/537.36",
                  "Accept": "application/json"})


def _get(path, params, tries=4):
    for _ in range(tries):
        try:
            r = S.get(f"{BASE}/{path}", params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(8); continue
        except Exception:
            time.sleep(3)
    return {}


def stage_fetch():
    """All finished CS2 series (bo>=3) since GRID_T0 with map1 result + map2 start."""
    done = pd.read_parquet(BO3_CACHE) if BO3_CACHE.exists() else pd.DataFrame()
    have = set(done.match_id) if len(done) else set()
    matches, page = [], 1
    while True:
        j = _get("matches", {"filter[matches.status][eq]": "finished",
                             "filter[matches.discipline_id][eq]": 1,
                             "sort": "-start_date", "page[limit]": 100,
                             "page[offset]": (page - 1) * 100})
        res = j.get("results") or []
        if not res:
            break
        stop = False
        for m in res:
            sd = pd.Timestamp(m.get("start_date"))
            if sd is pd.NaT:
                continue
            if sd < GRID_T0:
                stop = True; break
            if (m.get("bo_type") or 0) >= 3:
                matches.append(m)
        if stop:
            break
        page += 1
        time.sleep(0.3)
    todo = [m for m in matches if m["id"] not in have]
    print(f"[fetch] GRID-era finished bo3+ matches: {len(matches)}; new: {len(todo)}")
    rows = []
    for i, m in enumerate(todo, 1):
        jg = _get("games", {"filter[games.match_id][eq]": m["id"], "sort": "begin_at"})
        gs = [g for g in (jg.get("results") or []) if g.get("status") == "finished"
              and g.get("winner_clan_name")]
        if len(gs) < 2:
            continue
        g1, g2 = gs[0], gs[1]
        loser1 = None   # map-1 loser = the other team; recover from any later map
        names = {g.get("winner_clan_name") for g in gs} | {g.get("loser_clan_name")
                 for g in gs if g.get("loser_clan_name")}
        names.discard(None)
        if g1.get("loser_clan_name"):
            loser1 = g1["loser_clan_name"]
        else:
            others = names - {g1["winner_clan_name"]}
            loser1 = next(iter(others)) if len(others) == 1 else None
        if not loser1:
            continue
        rows.append(dict(match_id=m["id"], bo3_slug=m.get("slug"),
                         start_date=m.get("start_date"), tier=m.get("tier"),
                         map1_winner=g1["winner_clan_name"], map1_loser=loser1,
                         map2_begin=g2.get("begin_at"),
                         series_winner=gs[-1]["winner_clan_name"]))
        if i % 50 == 0:
            print(f"  {i}/{len(todo)} matches")
        time.sleep(0.25)
    df = pd.concat([done, pd.DataFrame(rows)], ignore_index=True) if len(done) else pd.DataFrame(rows)
    if len(df):
        df.to_parquet(BO3_CACHE, index=False)
    print(f"[fetch] cached: {len(df)} matches with map1+map2 data")


def stage_join():
    bo3 = pd.read_parquet(BO3_CACHE)
    uni = universe()
    uni = uni[uni.game == "cs2"]
    # index Polymarket markets by normalized team pair + date
    idx = {}
    for r in uni.itertuples(index=False):
        a, b = r.outcomes
        key = (min(_norm(a), _norm(b)), max(_norm(a), _norm(b)))
        idx.setdefault(key, []).append(r)
    res_p = ROOT / "cowork_snapshot" / "esports" / "resolutions.parquet"
    res = pd.read_parquet(res_p)
    res = res[res.winning_outcome.notna()][["slug", "winning_outcome"]].drop_duplicates("slug")
    win = dict(zip(res.slug, res.winning_outcome))

    rows, n_joined = [], 0
    for m in bo3.itertuples(index=False):
        key = (min(_norm(m.map1_winner), _norm(m.map1_loser)),
               max(_norm(m.map1_winner), _norm(m.map1_loser)))
        cands = idx.get(key) or []
        sd = pd.Timestamp(m.start_date)
        cand = next((c for c in cands if abs((c.gs - sd).total_seconds()) < 36 * 3600), None)
        if cand is None or pd.isna(pd.Timestamp(m.map2_begin)):
            continue
        fp = TR / f"{cand.condition_id}.parquet"
        if not fp.exists():
            continue
        t = pd.read_parquet(fp)
        if t.empty:
            continue
        n_joined += 1
        for c in ("ts", "price"):
            t[c] = pd.to_numeric(t[c], errors="coerce")
        t = t.dropna(subset=["ts", "price"])
        a, b = cand.outcomes
        # loser side of map 1, mapped onto the market outcomes
        loser_out = a if _norm(a) == _norm(m.map1_loser) else b
        t["pl"] = np.where(t.outcome.astype(str).map(_norm) == _norm(loser_out),
                           t.price, 1 - t.price)
        m2 = pd.Timestamp(m.map2_begin).value / 1e9
        w = t[(t.ts >= m2 - 600) & (t.ts <= m2 - 30)].sort_values("ts")
        if w.empty:
            continue
        price = float(w.pl.iloc[-1])
        if not (0.02 <= price <= 0.98):
            continue
        wn = win.get(cand.slug)
        if not isinstance(wn, str):
            continue
        rows.append(dict(slug=cand.slug, tier=m.tier, loser=loser_out, lp=price,
                         lw=int(_norm(wn) == _norm(loser_out)),
                         n_window_trades=len(w)))
    d = pd.DataFrame(rows)
    d.to_parquet(OUT / "inplay_tape_joined.parquet", index=False)
    print(f"[join] bo3 matches: {len(bo3)}; joined to a market with between-maps tape: {len(d)}")
    if not len(d):
        return
    def z_test(dd, label):
        if len(dd) < 5:
            print(f"  {label:24} n={len(dd)} (too small)"); return
        z = (dd.lw.sum() - dd.lp.sum()) / math.sqrt((dd.lp * (1 - dd.lp)).sum())
        p = 0.5 * math.erfc(z / math.sqrt(2))
        roi = np.mean(np.where(dd.lw == 1, (1 - dd.lp) / dd.lp, -1.0))
        print(f"  {label:24} n={len(dd):3d} implied={dd.lp.sum():.1f} actual={dd.lw.sum()} "
              f"z={z:+.2f} p={p:.4f} ROI={roi:+.1%}")
    print("  contrarian (buy map-1 loser at last between-maps fill):")
    z_test(d, "ALL")
    z_test(d[d.lp <= 0.30], "entry<=0.30")
    z_test(d[d.lp <= 0.15], "entry<=0.15")


STAGES = dict(fetch=stage_fetch, join=stage_join)
if __name__ == "__main__":
    for s in (sys.argv[1:] or list(STAGES)):
        STAGES[s]()
