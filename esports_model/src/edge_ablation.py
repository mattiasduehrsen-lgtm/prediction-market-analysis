"""Per-lever EDGE attribution: 5-seed-averaged preds per ablation -> R2-filtered
edge backtest on the CS2 market join. The money-metric complement to train.py."""
import numpy as np, pandas as pd, pyarrow.parquet as pq, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from train import ABLATIONS, fit_predict
import backtest_cs2 as B

ART = Path(__file__).resolve().parents[1] / "artifacts"
SEEDS = 5

def seed_avg_preds(df, feats):
    n = len(df); cut = int(n*0.8); val_cut = int(cut*0.85)
    tr, va, te = df.iloc[:val_cut], df.iloc[val_cut:cut], df.iloc[cut:]
    ps = [fit_predict(tr, va, te, feats, seed=s)[2] for s in range(SEEDS)]
    return te, np.mean(ps, 0)

def join_markets(te, p):
    preds = te[["match_id", "begin_at", "actualA"]].copy()
    preds["prob"] = p
    mt = pq.read_table(B.PS/"cs2_matches.parquet").to_pandas()[["match_id","teamA_name","teamB_name"]]
    preds = preds.merge(mt, on="match_id", how="left")
    preds["begin_at"] = pd.to_datetime(preds.begin_at, utc=True)
    preds["ps_normA"] = preds.teamA_name.map(B.norm); preds["ps_normB"] = preds.teamB_name.map(B.norm)
    preds["pair"] = [tuple(sorted(x)) for x in zip(preds.ps_normA, preds.ps_normB)]
    preds["date"] = preds.begin_at.dt.date
    pidx = {}
    for r in preds.itertuples(index=False): pidx.setdefault(r.pair, []).append(r)
    m = MKT
    one = pd.Timedelta(days=1).to_pytimedelta()
    rows = []
    for mm in m.itertuples(index=False):
        cands = []
        for d in (mm.date, mm.date-one, mm.date+one):
            cands += [x for x in pidx.get(mm.pair, []) if x.date == d]
        if not cands: continue
        x = cands[0]; flip = x.ps_normA != mm.mkt_normA
        o = lambda v: 1-v if flip else v
        rows.append(dict(condition_id=mm.condition_id, game_start=mm.game_start,
                         match_id=x.match_id, priceA=mm.priceA, priceB=mm.priceB,
                         prob=o(x.prob), A_won=int(o(x.actualA))))
    j = pd.DataFrame(rows).drop_duplicates("condition_id")
    j = j[j.game_start >= pd.Timestamp("2025-09-18", tz="UTC")]
    return j.merge(TIER, on="match_id", how="left")

def r2_stats(j, fee=0.02):
    rows = []
    for r in j.itertuples(index=False):
        s = r.priceA + r.priceB
        if s <= 0: continue
        pa, pb = r.priceA/s, r.priceB/s
        eA, eB = r.prob-pa, (1-r.prob)-pb
        if eA >= eB: gap, price, win = eA, pa+fee, r.A_won == 1
        else: gap, price, win = eB, pb+fee, r.A_won == 0
        if price >= 0.99 or price <= 0.01: continue
        rows.append(dict(gap=gap, price=price, ret=(1/price-1) if win else -1.0, tier=r.tier_ord))
    d = pd.DataFrame(rows)
    R2 = (d.price > 0.20) & d.tier.notna() & (d.tier < 4)
    def agg(x): return dict(n=len(x), roi=round(float(x.ret.mean()*100), 1) if len(x) else None,
                            pnl=round(float(x.ret.sum()), 1))
    return {"raw_mid": agg(d[(d.gap>=.05)&(d.gap<.15)]),
            "R2_mid": agg(d[R2&(d.gap>=.05)&(d.gap<.15)]),
            "R2_tail": agg(d[R2&(d.gap>=.15)]),
            "R2_all5c": agg(d[R2&(d.gap>=.05)])}

if __name__ == "__main__":
    df = pq.read_table(ART/"cs2_features.parquet").to_pandas()
    df["begin_at"] = pd.to_datetime(df.begin_at, utc=True)
    df = df.sort_values("begin_at").reset_index(drop=True)
    TIER = df[["match_id", "tier_ord"]]
    m = pq.read_table(B.GD/"polymarket_cs2_markets.parquet").to_pandas()
    m = m[(~m.is_single_map.astype(bool)) & (m.resolved.astype(bool))].copy()
    m["game_start"] = pd.to_datetime(m.game_start, utc=True)
    mk = B.market_pA_table(m); m = m.merge(mk, on="condition_id", how="inner")
    m["priceA"] = m.mkt_pA; m["priceB"] = 1-m.mkt_pA
    m["mkt_normA"] = m.teamA.map(B.norm); m["mkt_normB"] = m.teamB.map(B.norm)
    m["pair"] = [tuple(sorted(x)) for x in zip(m.mkt_normA, m.mkt_normB)]
    m["date"] = m.game_start.dt.date
    MKT = m
    out = {}
    for name, feats in ABLATIONS.items():
        te, p = seed_avg_preds(df, feats)
        j = join_markets(te, p)
        out[name] = r2_stats(j)
        print(f"{name:<10} {out[name]}")
    (ART/"edge_ablation_cs2.json").write_text(json.dumps(out, indent=2))
