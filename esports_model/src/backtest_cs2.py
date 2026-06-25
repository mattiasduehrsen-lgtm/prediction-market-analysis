"""CS2 edge-vs-market backtest, OOS only."""
import re, json
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]   # esports_model/src/ -> repo root
PS = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
GD = ROOT / "cowork_snapshot" / "gamedata"
ART = ROOT / "esports_model" / "artifacts"

def norm(s):
    if not isinstance(s, str): return ""
    s = s.split(" (")[0].split(" - ")[0]
    s = s.lower().strip()
    s = re.sub(r"\b(esports|esport|gaming|team|club|gg|e-sports)\b", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s

def market_pA_table(m):
    pp = pq.read_table(GD / "prematch_prices.parquet").to_pandas()
    pp = pp[pp.secs_before_start > 0].copy()
    pp = pp.merge(m[["condition_id", "teamA", "teamB"]], on="condition_id", how="inner")
    pp["nout"] = pp.outcome.map(norm)
    pp["is_A"] = pp.nout == pp.teamA.map(norm)
    pp["is_B"] = pp.nout == pp.teamB.map(norm)
    pp = pp[pp.is_A | pp.is_B]
    pp["mkt_pA"] = np.where(pp.is_A, pp.price, 1 - pp.price)
    pp = pp.sort_values("secs_before_start").groupby("condition_id", as_index=False).first()
    return pp[["condition_id", "mkt_pA", "secs_before_start"]]

def load_join():
    m = pq.read_table(GD / "polymarket_cs2_markets.parquet").to_pandas()
    m = m[(~m.is_single_map.astype(bool)) & (m.resolved.astype(bool))].copy()
    m["game_start"] = pd.to_datetime(m["game_start"], utc=True)
    mk = market_pA_table(m)
    m = m.merge(mk, on="condition_id", how="inner")
    m["priceA"] = m["mkt_pA"]; m["priceB"] = 1 - m["mkt_pA"]
    m["mkt_normA"] = m.teamA.map(norm); m["mkt_normB"] = m.teamB.map(norm)
    m["pair"] = m.apply(lambda r: tuple(sorted([r.mkt_normA, r.mkt_normB])), axis=1)
    m["date"] = m.game_start.dt.date
    preds = pq.read_table(ART / "cs2_oos_preds.parquet").to_pandas()
    mt = pq.read_table(PS / "cs2_matches.parquet").to_pandas()[["match_id", "teamA_name", "teamB_name"]]
    preds = preds.merge(mt, on="match_id", how="left")
    preds["begin_at"] = pd.to_datetime(preds["begin_at"], utc=True)
    preds["ps_normA"] = preds.teamA_name.map(norm); preds["ps_normB"] = preds.teamB_name.map(norm)
    preds["pair"] = preds.apply(lambda r: tuple(sorted([r.ps_normA, r.ps_normB])), axis=1)
    preds["date"] = preds.begin_at.dt.date
    pidx = {}
    for r in preds.itertuples(index=False):
        pidx.setdefault(r.pair, []).append(r)
    one = pd.Timedelta(days=1).to_pytimedelta()
    rows = []
    for mm in m.itertuples(index=False):
        cands = []
        for d in (mm.date, mm.date - one, mm.date + one):
            cands += [p for p in pidx.get(mm.pair, []) if p.date == d]
        if not cands: continue
        p = cands[0]
        if p.ps_normA == mm.mkt_normA:
            model_pA, base_pA, A_won = p.model_prob, p.base_prob, p.actualA
        else:
            model_pA, base_pA, A_won = 1 - p.model_prob, 1 - p.base_prob, 1 - p.actualA
        rows.append({"condition_id": mm.condition_id, "slug": mm.slug, "game_start": mm.game_start,
                     "priceA": mm.priceA, "priceB": mm.priceB,
                     "model_pA": model_pA, "base_pA": base_pA, "A_won": int(A_won)})
    return pd.DataFrame(rows).drop_duplicates("condition_id")

def backtest(j, prob_col, thresholds, fee=0.02):
    out = []
    for th in thresholds:
        bets = []
        for r in j.itertuples(index=False):
            mp = getattr(r, prob_col); pa, pb = r.priceA, r.priceB; s = pa + pb
            if s <= 0: continue
            pa, pb = pa / s, pb / s
            edgeA, edgeB = mp - pa, (1 - mp) - pb
            if edgeA >= th and edgeA >= edgeB: price, win = pa + fee, (r.A_won == 1)
            elif edgeB >= th: price, win = pb + fee, (r.A_won == 0)
            else: continue
            if price >= 0.99 or price <= 0.01: continue
            ret = (1.0 / price - 1.0) if win else -1.0
            bets.append((ret, win))
        if not bets:
            out.append({"threshold": round(th, 3), "n": 0}); continue
        rets = np.array([b[0] for b in bets])
        out.append({"threshold": round(th, 3), "n": len(bets),
                    "hit_rate": round(float(np.mean([b[1] for b in bets])), 4),
                    "roi_pct": round(float(rets.mean() * 100), 2),
                    "total_pnl": round(float(rets.sum()), 2)})
    return out

def dose_response(j, prob_col, fee=0.02):
    recs = []
    for r in j.itertuples(index=False):
        mp = getattr(r, prob_col); pa, pb = r.priceA, r.priceB; s = pa + pb
        if s <= 0: continue
        pa, pb = pa / s, pb / s
        edgeA, edgeB = mp - pa, (1 - mp) - pb
        if edgeA >= edgeB: gap, price, win = edgeA, pa + fee, (r.A_won == 1)
        else: gap, price, win = edgeB, pb + fee, (r.A_won == 0)
        if price >= 0.99 or price <= 0.01: continue
        ret = (1.0 / price - 1.0) if win else -1.0
        recs.append((gap, ret))
    d = pd.DataFrame(recs, columns=["gap", "ret"])
    bins = [-1, 0, 0.05, 0.10, 0.15, 0.20, 1]
    labels = ["<0", "0-5%", "5-10%", "10-15%", "15-20%", ">20%"]
    d["bucket"] = pd.cut(d.gap, bins=bins, labels=labels)
    g = d.groupby("bucket", observed=True).agg(n=("ret", "size"), roi_pct=("ret", lambda x: round(x.mean() * 100, 2)))
    return g.reset_index()

if __name__ == "__main__":
    j = load_join()
    j = j[j.game_start >= pd.Timestamp("2025-09-18", tz="UTC")]
    print(f"OOS CS2 series markets joined (model+price+result): {len(j)}")
    if len(j): print(f"window: {j.game_start.min().date()} -> {j.game_start.max().date()}")
    ths = [0.0, 0.03, 0.05, 0.08, 0.10, 0.15]
    res = {"n_markets": len(j), "model": backtest(j, "model_pA", ths), "baseline": backtest(j, "base_pA", ths)}
    print("\n=== MODEL: edge vs market ==="); print(pd.DataFrame(res["model"]).to_string(index=False))
    print("\n=== BASELINE Elo: edge vs market ==="); print(pd.DataFrame(res["baseline"]).to_string(index=False))
    print("\n=== MODEL dose-response (ROI by disagreement size) ===")
    dr = dose_response(j, "model_pA"); print(dr.to_string(index=False))
    res["dose_response"] = dr.to_dict("records")
    (ART / "edge_backtest_cs2.json").write_text(json.dumps(res, indent=2, default=str))
    j.to_parquet(ART / "cs2_edge_joined.parquet", index=False)
