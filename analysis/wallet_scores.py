"""Wallet-selection v2 — fill-true EB skill scores + out-of-time fade eval.

Design + pre-registered promotion bar: WALLET_SELECTION_V2_2026-07-13.md.
Requires the tape cache WITH wallet column (tape_backfill.py fetch, 2026-07-13+).

Stages:
  build  -> output/wallet_study/fills.parquet   (per-fill backed-outcome rows)
  score  -> output/wallet_study/scores.parquet  (per-wallet EB posteriors)
  eval   -> printed OOS comparison: v2 selection vs current fade_targets.json

Run: .venv\\Scripts\\python.exe -u analysis/wallet_scores.py [build score eval]
"""
import json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
from tape_backfill import universe, TR

OUT = ROOT / "output" / "wallet_study"
OUT.mkdir(parents=True, exist_ok=True)
RES = ROOT / "cowork_snapshot" / "esports" / "resolutions.parquet"
TARGETS = ROOT / "cowork_snapshot" / "esports" / "fade_targets.json"

SPLIT = pd.Timestamp("2026-07-06", tz="UTC")   # fit < SPLIT <= eval
AFTER_LO, AFTER_HI = 60, 600                   # achievable-price window (s)
MIN_MARKETS = 5                                # score eligibility
MM_FILLS_PER_DAY = 30
MM_TWO_SIDED_FRAC = 0.20
TOP_K = 300                                    # match current list size
MIN_POST_EDGE = 0.03                           # posterior fade-edge floor


def stage_build():
    uni = universe()
    res = pd.read_parquet(RES)
    res = res[res.winning_outcome.notna()][["slug", "winning_outcome"]].drop_duplicates("slug")
    win = dict(zip(res.slug, res.winning_outcome))
    rows = []
    for r in uni.itertuples(index=False):
        wn = win.get(r.slug)
        if not isinstance(wn, str):
            continue
        fp = TR / f"{r.condition_id}.parquet"
        if not fp.exists():
            continue
        t = pd.read_parquet(fp)
        if t.empty or "wallet" not in t.columns:
            continue
        for c in ("ts", "price"):
            t[c] = pd.to_numeric(t[c], errors="coerce")
        t = t.dropna(subset=["ts", "price", "wallet"]).sort_values("ts")
        a, b = r.outcomes
        na = str(a).strip().lower()
        is_a = t.outcome.astype(str).str.strip().str.lower() == na
        t["pa"] = np.where(is_a, t.price, 1 - t.price)          # prob of A
        # normalize action to "backed outcome at effective prob":
        # BUY X = back X at price(X); SELL X = back other at 1-price(X)
        buy = t.side.astype(str).str.upper() == "BUY"
        t["backed_a"] = np.where(buy, is_a, ~is_a)
        t["p_backed"] = np.where(t.backed_a, t.pa, 1 - t.pa)
        won_a = int(str(wn).strip().lower() == na)
        pa_arr, ts_arr = t.pa.to_numpy(), t.ts.to_numpy()
        for i in range(len(t)):
            # achievable price: last trade in (ts+60, ts+600]
            lo, hi = ts_arr[i] + AFTER_LO, ts_arr[i] + AFTER_HI
            j = np.searchsorted(ts_arr, hi, side="right") - 1
            if j <= i or ts_arr[j] < lo:
                continue
            row = t.iloc[i]
            pa_after = pa_arr[j]
            p_after = pa_after if row.backed_a else 1 - pa_after
            won_b = won_a if row.backed_a else 1 - won_a
            rows.append((row.wallet.lower(), r.slug, r.game, r.gs.value // 10**9,
                         float(row.ts), bool(row.backed_a), float(row.p_backed),
                         float(p_after), int(won_b)))
    d = pd.DataFrame(rows, columns=["wallet", "slug", "game", "gs", "ts",
                                    "backed_a", "p_backed", "p_after", "won"])
    d.to_parquet(OUT / "fills.parquet", index=False)
    print(f"[build] fills: {len(d):,} | wallets: {d.wallet.nunique():,} | "
          f"markets: {d.slug.nunique()}")


def _market_level(d):
    """One observation per (wallet, market, backed-side): mean fade edge."""
    d = d.copy()
    d["edge"] = d.p_after - d.won         # fade edge: + = fading them pays
    g = (d.groupby(["wallet", "slug", "backed_a"])
          .agg(edge=("edge", "mean"), p_backed=("p_backed", "mean"),
               gs=("gs", "first"), n_fills=("edge", "size")).reset_index())
    return g


def stage_score():
    d = pd.read_parquet(OUT / "fills.parquet")
    fit = d[pd.to_datetime(d.gs, unit="s", utc=True) < SPLIT]
    print(f"[score] fit fills: {len(fit):,} (< {SPLIT.date()})")
    # MM/bot structural signature on the fit window
    days = fit.groupby("wallet").ts.agg(lambda s: max((s.max() - s.min()) / 86400, 1))
    fpd = fit.groupby("wallet").size() / days
    both = (fit.groupby(["wallet", "slug"]).backed_a.nunique() == 2)
    two_frac = both.groupby("wallet").mean()
    mm = set(fpd[fpd > MM_FILLS_PER_DAY].index) | set(two_frac[two_frac > MM_TWO_SIDED_FRAC].index)

    m = _market_level(fit)
    st = (m.groupby("wallet")
           .agg(k=("edge", "size"), mean=("edge", "mean"), var=("edge", "var"),
                avg_price=("p_backed", "mean")).reset_index())
    st = st[st.k >= MIN_MARKETS].copy()
    st["var"] = st["var"].fillna(st["var"].median())
    st["se2"] = st["var"] / st.k
    # empirical Bayes: tau^2 via method of moments
    mu = float(np.average(st["mean"], weights=st.k))
    tau2 = max(float(st["mean"].var() - st.se2.mean()), 1e-6)
    st["post"] = (st["mean"] / st.se2 + mu / tau2) / (1 / st.se2 + 1 / tau2)
    st["is_mm"] = st.wallet.isin(mm)
    st = st.sort_values("post", ascending=False)
    st.to_parquet(OUT / "scores.parquet", index=False)
    el = st[~st.is_mm]
    print(f"[score] scored wallets (k>={MIN_MARKETS}): {len(st):,} "
          f"(MM-excluded: {int(st.is_mm.sum())}) | pop mean edge={mu:+.4f} "
          f"tau={np.sqrt(tau2):.4f}")
    print(f"  eligible with posterior >= {MIN_POST_EDGE}: "
          f"{int((el.post >= MIN_POST_EDGE).sum())}")
    print(el.head(10)[["wallet", "k", "mean", "post", "avg_price"]]
          .round(4).to_string(index=False))


def _simulate(fills, wallets, label, rng):
    """Fade the first selected-wallet fill per (market, backed-side) at the
    achievable complement price +1c. Cluster bootstrap by match."""
    f = fills[fills.wallet.isin(wallets)].sort_values("ts")
    f = f.drop_duplicates(["slug", "backed_a"], keep="first")
    cost = (1 - f.p_after + 0.01).clip(0.02, 0.99)
    win = 1 - f.won
    keep = (cost > 0.05) & (cost < 0.95)
    f, cost, win = f[keep], cost[keep], win[keep]
    if not len(f):
        print(f"  {label:34} n=0"); return
    pnl = np.where(win == 1, (1 - cost) / cost, -1.0)
    bym = pd.DataFrame({"m": f.slug.values, "p": pnl}).groupby("m").p.mean()
    boots = np.array([rng.choice(bym, len(bym), replace=True).mean() for _ in range(4000)])
    t = bym.mean() / (bym.std() / np.sqrt(len(bym))) if len(bym) > 3 else float("nan")
    print(f"  {label:34} bets={len(f):4d} matches={len(bym):3d} "
          f"ROI={pnl.mean():+.1%} clustered t={t:+.2f} P(<=0)={np.mean(boots <= 0):.3f}")


def stage_eval():
    d = pd.read_parquet(OUT / "fills.parquet")
    ev = d[pd.to_datetime(d.gs, unit="s", utc=True) >= SPLIT]
    print(f"[eval] eval-window fills: {len(ev):,} "
          f"({ev.slug.nunique()} markets, gs >= {SPLIT.date()})")
    st = pd.read_parquet(OUT / "scores.parquet")
    el = st[~st.is_mm & (st.post >= MIN_POST_EDGE)]
    v2 = set(el.head(TOP_K).wallet)
    cur = set(w.lower() for w in json.loads(TARGETS.read_text())["target_wallets"])
    print(f"  v2 selection: {len(v2)} wallets | current list: {len(cur)} | "
          f"overlap: {len(v2 & cur)}")
    rng = np.random.default_rng(7)
    _simulate(ev, v2, "v2 EB selection (OOS)", rng)
    _simulate(ev, cur, "CURRENT fade_targets (baseline)", rng)
    _simulate(ev, set(st.wallet), "ALL scored wallets (population)", rng)
    print("  promotion requires: v2 > baseline AND t>=2 AND repeat on a second "
          "window (~Jul 21). No list swap from this run.")


STAGES = dict(build=stage_build, score=stage_score, eval=stage_eval)
if __name__ == "__main__":
    for s in (sys.argv[1:] or list(STAGES)):
        STAGES[s]()
