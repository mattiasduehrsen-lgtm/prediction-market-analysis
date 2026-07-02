"""CS2 edge-vs-market backtest, OOS only. v2: compares v2 / v1 / baseline Elo."""
import re, json
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
PS = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
GD = ROOT / "cowork_snapshot" / "gamedata"
ART = ROOT / "esports_model" / "artifacts"

def norm(s):
    if not isinstance(s, str): return ""
    s = s.split(" (")[0].split(" - ")[0]
    s = s.lower().strip()
    s = re.sub(r"\b(esports|esport|gaming|team|club|gg|e-sports)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)

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

def load_join(pred_file="cs2_oos_preds_v2.parquet"):
    m = pq.read_table(GD / "polymarket_cs2_markets.parquet").to_pandas()
    m = m[(~m.is_single_map.astype(bool)) & (m.resolved.astype(bool))].copy()
    m["game_start"] = pd.to_datetime(m["game_start"], utc=True)
    mk = market_pA_table(m)
    m = m.merge(mk, on="condition_id", how="inner")
    m["priceA"] = m["mkt_pA"]; m["priceB"] = 1 - m["mkt_pA"]
    m["mkt_normA"] = m.teamA.map(norm); m["mkt_normB"] = m.teamB.map(norm)
    m["pair"] = m.apply(lambda r: tuple(sorted([r.mkt_normA, r.mkt_normB])), axis=1)
    m["date"] = m.game_start.dt.date
    preds = pq.read_table(ART / pred_file).to_pandas()
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
        flip = p.ps_normA != mm.mkt_normA
        def orient(v): return 1 - v if flip else v
        rows.append({"condition_id": mm.condition_id, "slug": mm.slug, "game_start": mm.game_start, "match_id": p.match_id,
                     "priceA": mm.priceA, "priceB": mm.priceB,
                     "model_pA": orient(p.model_prob), "v1_pA": orient(p.v1_prob),
                     "base_pA": orient(p.base_prob), "A_won": int(orient(p.actualA))})
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

def band_backtest(j, prob_col, lo, hi, fee=0.02):
    """Bets only where the disagreement falls in [lo, hi) -- the fillable band."""
    bets = []
    for r in j.itertuples(index=False):
        mp = getattr(r, prob_col); pa, pb = r.priceA, r.priceB; s = pa + pb
        if s <= 0: continue
        pa, pb = pa / s, pb / s
        edgeA, edgeB = mp - pa, (1 - mp) - pb
        gap = max(edgeA, edgeB)
        if not (lo <= gap < hi): continue
        if edgeA >= edgeB: price, win = pa + fee, (r.A_won == 1)
        else: price, win = pb + fee, (r.A_won == 0)
        if price >= 0.99 or price <= 0.01: continue
        ret = (1.0 / price - 1.0) if win else -1.0
        bets.append((ret, win))
    if not bets: return {"n": 0}
    rets = np.array([b[0] for b in bets])
    return {"n": len(bets), "hit_rate": round(float(np.mean([b[1] for b in bets])), 4),
            "roi_pct": round(float(rets.mean() * 100), 2),
            "total_pnl": round(float(rets.sum()), 2)}

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
    return d.groupby("bucket", observed=True).agg(
        n=("ret", "size"), roi_pct=("ret", lambda x: round(x.mean() * 100, 2))).reset_index()

def r2_backtest(j, prob_col, fee=0.02, min_price=0.20):
    """Backtest with the shipped decision layer: entry price > min_price (after
    vig-normalization + fee), tier known and < S. Reports mid/tail/all and halves."""
    rows = []
    for r in j.itertuples(index=False):
        mp = getattr(r, prob_col); pa, pb = r.priceA, r.priceB; s = pa + pb
        if s <= 0: continue
        pa, pb = pa / s, pb / s
        edgeA, edgeB = mp - pa, (1 - mp) - pb
        if edgeA >= edgeB: gap, price, win = edgeA, pa + fee, (r.A_won == 1)
        else: gap, price, win = edgeB, pb + fee, (r.A_won == 0)
        if price >= 0.99 or price <= 0.01: continue
        ok = (price > min_price) and pd.notna(r.tier_ord) and (r.tier_ord < 4)
        rows.append(dict(t=r.game_start, gap=gap, ok=ok,
                         ret=(1.0 / price - 1.0) if win else -1.0))
    d = pd.DataFrame(rows)
    cut = pd.Timestamp("2026-02-01", tz="UTC")
    def agg(x):
        return {"n": int(len(x)), "roi_pct": round(float(x.ret.mean() * 100), 2) if len(x) else None,
                "total_pnl": round(float(x.ret.sum()), 2)}
    out = {}
    for name, m in (("raw_mid", (d.gap >= .05) & (d.gap < .15)),
                    ("R2_mid", d.ok & (d.gap >= .05) & (d.gap < .15)),
                    ("R2_tail", d.ok & (d.gap >= .15)),
                    ("R2_all5c", d.ok & (d.gap >= .05))):
        out[name] = agg(d[m])
        out[name + "_fit"] = agg(d[m & (d.t < cut)])
        out[name + "_eval"] = agg(d[m & (d.t >= cut)])
    return out


if __name__ == "__main__":
    j = load_join()
    j = j[j.game_start >= pd.Timestamp("2025-09-18", tz="UTC")]
    import pyarrow.parquet as _pq
    tiers = _pq.read_table(ART / "cs2_bo3_join.parquet").to_pandas()[["match_id", "tier_ord"]]
    j = j.merge(tiers, on="match_id", how="left")
    print(f"OOS CS2 series markets joined: {len(j)}")
    if len(j): print(f"window: {j.game_start.min().date()} -> {j.game_start.max().date()}")
    ths = [0.0, 0.03, 0.05, 0.08, 0.10, 0.15]
    res = {"n_markets": len(j)}
    for name, col in (("v2_ship", "model_pA"), ("v1_current", "v1_pA"), ("baseline", "base_pA")):
        res[name] = backtest(j, col, ths)
        print(f"\n=== {name}: edge vs market ===")
        print(pd.DataFrame(res[name]).to_string(index=False))
        res[f"{name}_midrange_5_15"] = band_backtest(j, col, 0.05, 0.15)
        print(f"  mid-range 5-15c (unfiltered): {res[f'{name}_midrange_5_15']}")
        res[f"{name}_R2"] = r2_backtest(j, col)
        for k in ("R2_mid", "R2_tail", "R2_all5c"):
            v = res[f"{name}_R2"]
            print(f"  {k:<9}: {v[k]}  fit={v[k+'_fit']}  eval={v[k+'_eval']}")
        dr = dose_response(j, col)
        res[f"{name}_dose"] = dr.to_dict("records")
        print(dr.to_string(index=False))
    (ART / "edge_backtest_cs2_v2.json").write_text(json.dumps(res, indent=2, default=str))
    j.to_parquet(ART / "cs2_edge_joined_v2.parquet", index=False)
