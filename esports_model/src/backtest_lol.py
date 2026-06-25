"""LoL edge-vs-market backtest, OOS only. Mirrors backtest_cs2.py.

IMPORTANT (the honest data reality, 2026-06-24): we have LoL match OUTCOMES (the
LoL win-prob model is validated on those) and 3k+ resolved LoL *series* markets,
but **no historical LoL pre-match PRICES** — `prematch_prices.parquet` is CS2-only
(0 LoL rows), because LoL was never traded/observed on Polymarket until the GRID
expansion days ago. So this backtest is FORWARD-LOOKING: it joins the LoL model's
OOS preds to whatever logged LoL pre-match prices exist, which is ~0 today and
will accumulate from two sources as matches play out:
  - prematch_prices.parquet (if/when a price logger covers LoL), and
  - output/esports_fade/lol_observations.csv (the observe-only bot, which already
    logs LoL series market price + model edge + book depth as targets trade).
The harness below runs the moment that data exists; today it reports ~0 markets.
"""
import re, json, sys
from pathlib import Path
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from backtest_cs2 import norm, backtest, dose_response   # shared, game-agnostic

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "esports_model" / "artifacts"
MK = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
PREMATCH = ROOT / "cowork_snapshot" / "gamedata" / "prematch_prices.parquet"
PS = ROOT / "cowork_snapshot" / "gamedata" / "pandascore"
# the observe-only bot's live LoL log (forward-looking price source); on the laptop
OBS = ROOT / "output" / "esports_fade" / "lol_observations.csv"
PROP = re.compile(r"-game\d|kill-over|first-blood|-map-|handicap|total-|-map\b", re.I)


def lol_resolved_series():
    """Resolved LoL SERIES (moneyline) markets with the winning team, from tokens."""
    m = pq.read_table(MK).to_pandas()
    m = m[m.slug.str.contains("lol-|league-of-legends", case=False, na=False)]
    m = m[~m.slug.str.contains("vct|valorant", case=False, na=False)]
    m = m[m.slug.map(lambda s: bool(s) and not PROP.search(s) and not s.startswith("will-"))]
    m = m[~m.archived.astype(bool)]
    rows = []
    for r in m.itertuples(index=False):
        toks = [t for t in (list(r.tokens) if r.tokens is not None else []) if t.get("outcome")]
        if len(toks) != 2:
            continue
        a, b = toks[0], toks[1]
        # teamA/teamB only — the OUTCOME comes from the PandaScore result in the
        # model preds (like backtest_cs2), not the raw market winner flag (which is
        # not reliably set in this structure snapshot). The pred join also filters
        # to matches that actually happened, so no separate "resolved" gate needed.
        rows.append({"condition_id": r.condition_id, "slug": r.slug, "game_start": r.game_start,
                     "teamA": a["outcome"], "teamB": b["outcome"]})
    return pd.DataFrame(rows)


def lol_prices():
    """Pre-match LoL prices, mkt_pA per condition_id, from any source we have."""
    frames = []
    # source 1: prematch_prices.parquet (CS2-only today -> 0 LoL)
    if PREMATCH.exists():
        pp = pq.read_table(PREMATCH).to_pandas()
        pp = pp[pp.secs_before_start > 0][["condition_id", "outcome", "price"]]
        frames.append(pp)
    # source 2: the observe-only bot's lol_observations.csv (forward-looking).
    # our_entry is the price we'd pay for our_outcome (the bought side).
    if OBS.exists():
        try:
            o = pd.read_csv(OBS)
            o = o[o.our_entry.notna()][["condition_id", "our_outcome", "our_entry"]]
            o = o.rename(columns={"our_outcome": "outcome", "our_entry": "price"})
            frames.append(o)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame(columns=["condition_id", "outcome", "price"])
    return pd.concat(frames, ignore_index=True)


def load_join():
    mk = lol_resolved_series()
    px = lol_prices()
    n_resolved = len(mk)                       # raw LoL series markets (outcomes via PandaScore)
    if mk.empty or px.empty:
        return pd.DataFrame(), n_resolved, 0   # 0 with a logged pre-match price
    mk["normA"] = mk.teamA.map(norm); mk["normB"] = mk.teamB.map(norm)
    px["nout"] = px.outcome.map(norm)
    px = px.merge(mk[["condition_id", "normA", "normB"]], on="condition_id", how="inner")
    px = px[(px.nout == px.normA) | (px.nout == px.normB)]
    px["mkt_pA"] = np.where(px.nout == px.normA, px.price, 1 - px.price)
    px = px.groupby("condition_id", as_index=False).mkt_pA.first()
    n_priced = len(px)                         # LoL markets that have a logged price
    mk = mk.merge(px, on="condition_id", how="inner")
    mk["priceA"] = mk.mkt_pA; mk["priceB"] = 1 - mk.mkt_pA
    mk["pair"] = mk.apply(lambda r: tuple(sorted([r.normA, r.normB])), axis=1)
    mk["game_start"] = pd.to_datetime(mk.game_start, utc=True)
    mk["date"] = mk.game_start.dt.date
    preds = pq.read_table(ART / "lol_oos_preds.parquet").to_pandas()
    mt = pq.read_table(PS / "lol_matches.parquet").to_pandas()[["match_id", "teamA_name", "teamB_name"]]
    preds = preds.merge(mt, on="match_id", how="left")
    preds["begin_at"] = pd.to_datetime(preds["begin_at"], utc=True)
    preds["pA"] = preds.teamA_name.map(norm); preds["pB"] = preds.teamB_name.map(norm)
    preds["pair"] = preds.apply(lambda r: tuple(sorted([r.pA, r.pB])), axis=1)
    preds["date"] = preds.begin_at.dt.date
    pidx = {}
    for r in preds.itertuples(index=False):
        pidx.setdefault(r.pair, []).append(r)
    one = pd.Timedelta(days=1).to_pytimedelta()
    rows = []
    for mm in mk.itertuples(index=False):
        cands = [p for d in (mm.date, mm.date - one, mm.date + one)
                 for p in pidx.get(mm.pair, []) if p.date == d]
        if not cands:
            continue
        p = cands[0]
        if p.pA == mm.normA:
            model_pA, base_pA, A_won = p.model_prob, p.base_prob, p.actualA
        else:
            model_pA, base_pA, A_won = 1 - p.model_prob, 1 - p.base_prob, 1 - p.actualA
        rows.append({"condition_id": mm.condition_id, "slug": mm.slug, "game_start": mm.game_start,
                     "priceA": mm.priceA, "priceB": mm.priceB,
                     "model_pA": model_pA, "base_pA": base_pA, "A_won": int(A_won)})
    return pd.DataFrame(rows).drop_duplicates("condition_id"), n_resolved, n_priced


if __name__ == "__main__":
    j, n_markets, n_priced = load_join()
    print(f"resolved LoL series markets: {n_markets} | with logged pre-match price: {n_priced} | joined to model: {len(j)}")
    res = {"n_resolved_series": int(n_markets), "n_priced": int(n_priced), "n_joined": int(len(j))}
    if len(j) >= 20:
        ths = [0.0, 0.03, 0.05, 0.08, 0.10, 0.15]
        res["model"] = backtest(j, "model_pA", ths)
        res["baseline"] = backtest(j, "base_pA", ths)
        res["dose_response"] = dose_response(j, "model_pA").to_dict("records")
        print("\n=== MODEL: edge vs market ===");    print(pd.DataFrame(res["model"]).to_string(index=False))
        print("\n=== BASELINE Elo: edge vs market ==="); print(pd.DataFrame(res["baseline"]).to_string(index=False))
        print("\n=== dose-response ==="); print(dose_response(j, "model_pA").to_string(index=False))
    else:
        print("\nNot enough priced+resolved LoL markets to backtest yet (need >=20).")
        print("FORWARD-LOOKING: this fills in as the observe-only bot logs LoL series prices")
        print("(output/esports_fade/lol_observations.csv) and those matches resolve.")
    (ART / "edge_backtest_lol.json").write_text(json.dumps(res, indent=2, default=str))
