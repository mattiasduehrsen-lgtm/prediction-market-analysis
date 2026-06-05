"""PHASE 1c: does the map model beat Polymarket MAP-winner prices?

Join: Polymarket 'Map N Winner' market  <->  bo3 game (same teams, date, map N).
The bo3 game (from cs2_map_elo_history) gives the model's pre-map probability
AND the map identity (de_mirage etc.). Compare to the Polymarket pre-map price.

Tests BOTH:
  - map-AWARE model (p_map)
  - map-AGNOSTIC model (p_overall, team strength only)
so we learn whether ANY model beats the map market, and whether map-awareness adds.
"""
from __future__ import annotations
import re, glob
from pathlib import Path
from collections import defaultdict
import pandas as pd
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cs2_model import norm, teq

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
GD = ROOT / "cowork_snapshot" / "gamedata"
MAP_RE = re.compile(r"map\s*(\d+)", re.IGNORECASE)

def main():
    hist = pd.read_parquet(GD / "cs2_map_elo_history.parquet")
    hist["date"] = pd.to_datetime(hist["begin_at"], utc=True, errors="coerce").dt.floor("D")
    hist["nA"] = hist["teamA"].map(norm); hist["nB"] = hist["teamB"].map(norm)
    # index bo3 games by day for windowed fuzzy match
    by_day = defaultdict(list)
    for r in hist.itertuples(index=False):
        if pd.notna(r.date):
            by_day[r.date.toordinal()].append(r)

    mk = pd.read_parquet(GD / "polymarket_cs2_markets.parquet")
    mk = mk[mk["is_single_map"] & mk["resolved"].fillna(False)
            & mk["winning_outcome"].notna() & mk["game_start"].notna()].copy()
    mk["map_no"] = mk["question"].fillna("").apply(
        lambda q: int(MAP_RE.search(q).group(1)) if MAP_RE.search(q) else None)
    mk = mk[mk["map_no"].notna()]
    print(f"polymarket single-map markets (resolved, map# parsed): {len(mk)}")

    # pre-map prices from shards for these cids
    cids = set(mk["condition_id"])
    start_by_cid = dict(zip(mk["condition_id"], mk["game_start"].astype("int64") // 10**9))
    best = {}
    shards = sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet")))
    for sh in shards:
        try:
            d = pd.read_parquet(sh, columns=["conditionId", "outcome", "price", "timestamp"])
        except Exception:
            continue
        d = d[d["conditionId"].isin(cids)]
        if not len(d):
            continue
        d["timestamp"] = pd.to_numeric(d["timestamp"], errors="coerce")
        d["price"] = pd.to_numeric(d["price"], errors="coerce")
        for r in d.dropna(subset=["timestamp", "price"]).itertuples(index=False):
            gs = start_by_cid.get(r.conditionId)
            if gs is None or r.timestamp >= gs:
                continue
            k = (r.conditionId, r.outcome)
            if k not in best or r.timestamp > best[k][0]:
                best[k] = (r.timestamp, float(r.price))
    px = {k: v[1] for k, v in best.items()}
    print(f"pre-map prices for {len(set(k[0] for k in px))} markets")

    joined = []
    for r in mk.itertuples(index=False):
        nA, nB = norm(r.teamA), norm(r.teamB)
        gd = pd.Timestamp(r.game_start).floor("D"); god = gd.toordinal()
        match = None
        for dd in range(-2, 3):
            for c in by_day.get(god + dd, []):
                if int(c.number or -1) != int(r.map_no):
                    continue
                if (teq(nA, c.nA) and teq(nB, c.nB)) or (teq(nA, c.nB) and teq(nB, c.nA)):
                    match = c; break
            if match:
                break
        if not match:
            continue
        # orient model prob to Polymarket teamA
        if teq(nA, match.nA):
            p_map, p_ov = match.p_map, match.p_overall
        else:
            p_map, p_ov = 1 - match.p_map, 1 - match.p_overall
        mpx = px.get((r.condition_id, r.teamA))
        if mpx is None:
            mb = px.get((r.condition_id, r.teamB))
            mpx = (1 - mb) if mb is not None else None
        if mpx is None or not (0.03 < mpx < 0.97):
            continue
        A_won = 1 if r.winning_outcome == r.teamA else 0
        joined.append({"cid": r.condition_id, "map": match.map, "map_no": int(r.map_no),
                       "p_map": p_map, "p_overall": p_ov, "market": mpx, "A_won": A_won,
                       "ts": pd.Timestamp(r.game_start).value})
    j = pd.DataFrame(joined)
    print(f"joined map markets (model + price + outcome): {len(j)}")
    if not len(j):
        print("no joins — need full bo3 download (warmup) to overlap the 2025-06+ market window")
        return
    j.to_parquet(GD / "map_feasibility_joined.parquet")

    def roi(bets):
        cost = pnl = 0.0; n = w = 0
        for price, won in bets:
            cost += price; pnl += (1 - price) if won else -price; n += 1; w += won
        return n, (w/max(n,1)*100), (pnl/max(cost,1e-9)*100)

    def run_set(d, model_col, thr):
        bets = []
        for r in d.itertuples(index=False):
            mp = getattr(r, model_col); edge = mp - r.market
            if abs(edge) <= thr:
                continue
            if edge > 0:
                price = min(0.99, r.market + 0.02); won = r.A_won
            else:
                price = min(0.99, (1 - r.market) + 0.02); won = 1 - r.A_won
            bets.append((price, won))
        return roi(bets)

    for model_col in ["p_map", "p_overall"]:
        print(f"\n=== betting with {model_col} (slip 2c) ===")
        print(f"  {'thr':>5}{'bets':>6}{'WR':>6}{'ROI':>8}")
        for thr in [0.0, 0.10, 0.15, 0.20]:
            n, wr, rr = run_set(j, model_col, thr)
            print(f"  {thr:>5.2f}{n:>6}{wr:>5.0f}%{rr:>+7.1f}%")

    # OUT-OF-SAMPLE time split — the real rigor check
    js = j.sort_values("ts")
    cut = int(len(js) * 0.6)
    train, test = js.iloc[:cut], js.iloc[cut:]
    print(f"\n=== OUT-OF-SAMPLE (train={len(train)}, test={len(test)}, thr 0.15, slip 2c) ===")
    for model_col in ["p_map", "p_overall"]:
        nt, wrt, rrt = run_set(train, model_col, 0.15)
        nv, wrv, rrv = run_set(test, model_col, 0.15)
        print(f"  {model_col:<11} TRAIN n={nt:>3} ROI {rrt:>+6.1f}%   TEST n={nv:>3} ROI {rrv:>+6.1f}%")

if __name__ == "__main__":
    main()
