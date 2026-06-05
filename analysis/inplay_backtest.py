"""IN-PLAY series repricing backtest (the headline bo3 use).

Thesis: after map 1 of a Bo3, the series-winner price swings. Our model gives a
calibrated post-map-1 probability. If the market over/under-reacts, we bet.

Pipeline:
  pre-match series prob (our proven series model, from feasibility_joined)
    -> invert to single-map prob p  [P_series = p^2*(3-2p) for Bo3]
  bo3 timeline -> who won map 1, and WHEN it completed (~ map 2 begin_at)
  live model prob after map 1:  A up 1-0 -> 2p - p^2 ;  A down 0-1 -> p^2
  market price for teamA at ~t1 (first trade >= t1 from shards)
  outcome: did teamA win the series?
Backtest betting the divergence: ROI by edge threshold + OOS + 2c friction.
"""
from __future__ import annotations
import json, glob
from pathlib import Path
from collections import defaultdict
import pandas as pd
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cs2_model import norm, teq

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
BO3 = ROOT / "cowork_snapshot" / "gamedata" / "bo3"
GD = ROOT / "cowork_snapshot" / "gamedata"

def invert_bo3(P):
    """single-map p such that p^2*(3-2p) = P (monotonic in [0,1])."""
    lo, hi = 0.0, 1.0
    for _ in range(40):
        m = (lo + hi) / 2
        if m*m*(3 - 2*m) < P: lo = m
        else: hi = m
    return (lo + hi) / 2

def main():
    # bo_type per match (filter to Bo3)
    botype = {}
    mp = BO3 / "matches.jsonl"
    if mp.exists():
        for l in mp.read_text(encoding="utf-8").splitlines():
            try: m = json.loads(l)
            except Exception: continue
            botype[m.get("id")] = m.get("bo_type")

    # bo3 timelines: match_id -> sorted maps; keep map1 winner + t1 (map2 begin)
    games = defaultdict(list)
    for l in (BO3 / "games.jsonl").read_text(encoding="utf-8").splitlines():
        try: g = json.loads(l)
        except Exception: continue
        if g.get("game_version") != 2: continue
        if not (g.get("winner_clan_name") and g.get("loser_clan_name")
                and g.get("begin_at") and g.get("number")): continue
        games[g["match_id"]].append(g)

    # index by (teamset, date) -> (map1_winner_norm, t1_epoch)
    idx = defaultdict(list)
    for mid, gs in games.items():
        if botype and botype.get(mid) not in (3, None):  # Bo3 only when known
            continue
        gs = sorted(gs, key=lambda x: x["number"])
        if len(gs) < 2:
            continue
        g1, g2 = gs[0], gs[1]
        w, l = g1["winner_clan_name"].strip(), g1["loser_clan_name"].strip()
        t1 = pd.Timestamp(g2["begin_at"]).value // 10**9   # map1 completion ~ map2 start
        date = pd.Timestamp(g1["begin_at"]).floor("D")
        idx[frozenset((norm(w), norm(l)))].append(
            {"date": date, "winner": norm(w), "t1": t1})

    # our series model pre-match probs + outcomes
    fj = pd.read_parquet(GD / "feasibility_joined.parquet")  # cid, teamA, teamB, model_pA, A_won, ts_start
    mk = pd.read_parquet(GD / "polymarket_cs2_markets.parquet")[
        ["condition_id", "teamA", "teamB", "game_start", "winning_outcome"]]
    fj = fj.merge(mk, left_on="cid", right_on="condition_id", how="left", suffixes=("", "_m"))

    # find map1 result + t1 for each market
    rows = []
    for r in fj.itertuples(index=False):
        nA, nB = norm(r.teamA), norm(r.teamB)
        cands = idx.get(frozenset((nA, nB)))
        if not cands or pd.isna(r.game_start):
            continue
        gd = pd.Timestamp(r.game_start).floor("D")
        c = min(cands, key=lambda x: abs((x["date"] - gd).days))
        if abs((c["date"] - gd).days) > 1:
            continue
        p = invert_bo3(min(max(r.model_pA, 0.02), 0.98))
        a_won_map1 = teq(nA, c["winner"])
        live = (2*p - p*p) if a_won_map1 else (p*p)   # P(A wins series | post map1)
        rows.append({"cid": r.cid, "teamA": r.teamA, "model_pre": r.model_pA,
                     "p": p, "a_won_map1": a_won_map1, "model_live": live,
                     "t1": c["t1"], "A_won": int(r.A_won),
                     "game_start": pd.Timestamp(r.game_start).value // 10**9})
    df = pd.DataFrame(rows)
    print(f"series markets matched to a bo3 Bo3 timeline: {len(df)}")
    if not len(df):
        return

    # market price for teamA at ~t1 (first trade >= t1, within 30min) from shards
    cids = set(df["cid"])
    want = {(r.cid, r.teamA): r.t1 for r in df.itertuples(index=False)}
    teamA_by_cid = dict(zip(df["cid"], df["teamA"]))
    price_at = {}
    for sh in sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet"))):
        try:
            d = pd.read_parquet(sh, columns=["conditionId", "outcome", "price", "timestamp"])
        except Exception:
            continue
        d = d[d["conditionId"].isin(cids)]
        if not len(d): continue
        d["timestamp"] = pd.to_numeric(d["timestamp"], errors="coerce")
        d["price"] = pd.to_numeric(d["price"], errors="coerce")
        for r in d.dropna(subset=["timestamp", "price"]).itertuples(index=False):
            if r.outcome != teamA_by_cid.get(r.conditionId): continue
            t1 = want.get((r.conditionId, r.outcome))
            if t1 is None or r.timestamp < t1 or r.timestamp > t1 + 1800: continue
            k = r.conditionId
            if k not in price_at or r.timestamp < price_at[k][0]:
                price_at[k] = (r.timestamp, float(r.price))
    df["market_live"] = df["cid"].map(lambda c: price_at.get(c, (None, None))[1])
    j = df[df["market_live"].notna() & df["market_live"].between(0.02, 0.98)].copy()
    print(f"with a post-map1 market price: {len(j)}")
    if not len(j):
        print("no mid-match prices found in shards near map-1 completion")
        return
    j.to_parquet(GD / "inplay_joined.parquet")

    def roi(bets):
        cost = pnl = 0.0; n = w = 0
        for price, won in bets:
            cost += price; pnl += (1-price) if won else -price; n += 1; w += won
        return n, (w/max(n,1)*100), (pnl/max(cost,1e-9)*100)
    def run(d, thr):
        bets = []
        for r in d.itertuples(index=False):
            edge = r.model_live - r.market_live
            if abs(edge) <= thr: continue
            if edge > 0: price = min(0.99, r.market_live + 0.02); won = r.A_won
            else:        price = min(0.99, (1 - r.market_live) + 0.02); won = 1 - r.A_won
            bets.append((price, won))
        return roi(bets)

    print("\n=== IN-PLAY post-map-1 repricing (model_live vs market, 2c slip) ===")
    print(f"  {'thr':>5}{'bets':>6}{'WR':>6}{'ROI':>8}")
    for thr in [0.0, 0.05, 0.10, 0.15]:
        n, wr, rr = run(j, thr)
        print(f"  {thr:>5.2f}{n:>6}{wr:>5.0f}%{rr:>+7.1f}%")
    js = j.sort_values("game_start"); cut = int(len(js)*0.6)
    tr, te = js.iloc[:cut], js.iloc[cut:]
    print(f"\n  OOS (train={len(tr)}, test={len(te)}, thr 0.05):")
    nt = run(tr, 0.05); nv = run(te, 0.05)
    print(f"    TRAIN n={nt[0]} ROI {nt[2]:+.1f}%   TEST n={nv[0]} ROI {nv[2]:+.1f}%")
    # how much does the market move vs the model after map1? (does opportunity exist?)
    j["mkt_vs_model"] = (j["market_live"] - j["model_live"]).abs()
    print(f"\n  avg |market - model_live| after map1: {j['mkt_vs_model'].mean():.3f}  "
          f"(bigger = more mispricing to exploit)")

if __name__ == "__main__":
    main()
