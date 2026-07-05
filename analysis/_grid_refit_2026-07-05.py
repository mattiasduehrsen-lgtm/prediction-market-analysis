"""GRID-era gate re-fit — consolidated reproduction (Cowork session 2026-07-05).

Reproduces the numbers in COWORK_GRID_REFIT_RESULTS_2026-07-05.md from the
cowork_snapshot alone. Stages: signals capture lever1 lever2 lever3 lever4 lever5 pnl
Usage:  python analysis/_grid_refit_2026-07-05.py [stage ...]     (default: all)
Run from repo root (dev PC or laptop). Requires pandas/pyarrow/scipy/scikit-learn.
NOTE: the in-play PRE-REGISTERED gate is NOT here — run analysis/_inplay_sig.py on
the laptop (needs output/cs2_inplay/paper_results.csv, absent from the snapshot).
"""
import json, math, re, sys, glob, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "cowork_snapshot"
OUT = ROOT / "output" / "grid_refit"
OUT.mkdir(parents=True, exist_ok=True)
GRID_T0 = 1782172800  # 2026-06-23 00:00 UTC
JULY = "2026-07-01"

def _win_map():
    res = pd.read_parquet(SNAP / "esports/resolutions.parquet")
    res = res[res.winning_outcome.notna()][["slug", "winning_outcome"]].drop_duplicates("slug")
    return dict(zip(res.slug, res.winning_outcome))

def _outmap():
    mk = pd.read_parquet(SNAP / "esports/clob_esports_markets.parquet")[["slug", "tokens"]].drop_duplicates("slug")
    def outs(t):
        try:
            return [x.get("outcome") for x in (json.loads(t) if isinstance(t, str) else t)]
        except Exception:
            return []
    return dict(zip(mk.slug, mk.tokens.map(outs)))

def _predictors():
    sys.path.insert(0, str(ROOT / "esports_model" / "src"))
    from predict import Predictor
    return {g: Predictor(g) for g in ("cs2", "lol")}

def _game(slug): return "lol" if str(slug).startswith(("lol-", "arch-lol-")) else "cs2"
def _brier(p, y): return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))

# ── stage: signals ──────────────────────────────────────────────────────────
def stage_signals():
    win = _win_map()
    rows = []
    with (SNAP / "live/fade_events.jsonl").open(encoding="utf-8") as f:
        for line in f:
            try: e = json.loads(line)
            except Exception: continue
            t = e.get("type")
            if t == "shadow_compare" and e.get("shadow_ok"):
                rows.append(dict(src="shadow", ts=e.get("ts"), slug=e.get("slug"),
                                 game=e.get("game"), outcome=e.get("our_outcome"),
                                 entry=e.get("our_entry"), elo_p=e.get("elo_p"), v2_p=e.get("shadow_p")))
            elif t in ("model_filter_pass", "skip_model_filter"):
                rows.append(dict(src=t, ts=e.get("ts"), slug=e.get("slug"), game=_game(e.get("slug")),
                                 outcome=e.get("our_outcome"), entry=e.get("our_entry"),
                                 elo_p=None, v2_p=e.get("model_p")))
            elif t == "lol_observation":
                rows.append(dict(src="lol_obs", ts=e.get("ts"), slug=e.get("slug"), game="lol",
                                 outcome=e.get("our_outcome"), entry=e.get("our_entry"),
                                 elo_p=None, v2_p=e.get("model_p")))
    df = pd.DataFrame(rows)
    for c in ("ts", "entry", "elo_p", "v2_p"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["ts", "slug", "outcome", "entry"])
    w = df.slug.map(win)
    df["resolved"] = w.notna()
    df["won"] = [int(str(a).strip().lower() == str(b).strip().lower()) if isinstance(b, str) else np.nan
                 for a, b in zip(df.outcome, w)]
    df = df[df.ts >= GRID_T0]
    rank = {"shadow": 0, "model_filter_pass": 1, "skip_model_filter": 1, "lol_obs": 2}
    df["rank"] = df.src.map(rank)
    df = df.sort_values(["rank", "ts"]).drop_duplicates(["slug", "outcome"], keep="first")
    df = df[df.resolved].copy()
    df["date"] = pd.to_datetime(df.ts, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    # games counts + tier
    P = _predictors()
    outmap = _outmap()
    def games(team, g):
        r = P[g]._row(team)
        return int(r.games) if r is not None else np.nan
    def other_of(slug, outcome):
        for o in outmap.get(slug) or []:
            if isinstance(o, str) and o.strip().lower() != str(outcome).strip().lower():
                return o
    df["games_ours"] = [games(o, g) for o, g in zip(df.outcome, df.game)]
    df["games_other"] = [games(other_of(s, o), g) if other_of(s, o) else np.nan
                         for s, o, g in zip(df.slug, df.outcome, df.game)]
    df["min_games"] = df[["games_ours", "games_other"]].min(axis=1)
    tier = pd.read_parquet(SNAP / "gamedata/bo3/tier_index.parquet")
    tmap = {(r.a, r.b, r.date): r.tier_ord for r in tier.itertuples(index=False)}
    def norm(s):
        if not isinstance(s, str): return ""
        s = re.sub(r"\b(esports|esport|e sports|gaming|team|clan|club|gg)\b", " ", s.lower())
        return re.sub(r"[^a-z0-9]", "", s)
    DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
    def tier_for(slug, outcome, g):
        if g != "cs2": return np.nan
        oth = other_of(slug, outcome); m = DATE_RE.search(slug or "")
        if not oth or not m: return np.nan
        d0 = pd.Timestamp(m.group(0)); na, nb = norm(outcome), norm(oth)
        a, b = min(na, nb), max(na, nb)
        for dd in (0, 1, -1):
            t = tmap.get((a, b, (d0 + pd.Timedelta(days=dd)).strftime("%Y-%m-%d")))
            if t is not None: return t
        return np.nan
    df["tier_ord"] = [tier_for(s, o, g) for s, o, g in zip(df.slug, df.outcome, df.game)]
    df.to_parquet(OUT / "signals.parquet", index=False)
    sh = df[df.src == "shadow"].dropna(subset=["elo_p", "v2_p"])
    print(f"[signals] GRID-era resolved unique (slug,outcome): {len(df)}; shadow-with-both-probs: {len(sh)}")
    for c in ("entry", "elo_p", "v2_p"):
        print(f"  shadow Brier {c:6}: {_brier(sh[c].clip(.02,.98), sh.won):.4f}")

# ── stage: capture ──────────────────────────────────────────────────────────
def _classify(slug):
    s = slug or ""
    if "handicap" in s: return "handicap"
    if "round-total" in s or "total-games" in s or "kill-over" in s or "kill-under" in s: return "totals"
    if "kill" in s: return "kills"
    if "first-" in s or "first" in s.split("-")[-1:][0:1]: return "firsts"
    if re.search(r"game\d+$", s): return "map_winner"
    if re.search(r"-(slay|destroy|baron|dragon|inhibitor|ace)", s): return "occurrence"
    return "series"

def stage_capture():
    win = _win_map()
    recs = []
    for fp in sorted(glob.glob(str(SNAP / "live/price_capture/prices_*.jsonl"))):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                try: recs.append(json.loads(line))
                except Exception: pass
    df = pd.DataFrame(recs)
    df["gs_ts"] = pd.to_datetime(df.gs, utc=True, errors="coerce").astype("int64") / 1e9
    df["tmin"] = (df.gs_ts - df.ts) / 60.0
    rows = []
    for (cid, outcome), g in df.groupby(["cid", "outcome"], sort=False):
        g = g.sort_values("ts"); slug = g.slug.iloc[0]
        pre = g[(g.tmin >= 0) & (g.tmin <= 90)]
        if pre.empty: continue
        row = dict(cid=cid, outcome=outcome, slug=slug, prop=int(g.prop.iloc[0]),
                   cls=_classify(slug), gs_ts=g.gs_ts.iloc[0])
        for mark, lo, hi in (("t15", 12, 25), ("t5", 3, 8), ("t1", 0, 3)):
            w = pre[(pre.tmin >= lo) & (pre.tmin <= hi)]
            if len(w):
                last = w.iloc[-1]
                row.update({f"{mark}_bid": last.bid, f"{mark}_ask": last.ask,
                            f"{mark}_bdep": last.bid_depth, f"{mark}_adep": last.ask_depth})
        w = win.get(slug)
        row["resolved"] = isinstance(w, str)
        row["won"] = int(str(w).strip().lower() == str(outcome).strip().lower()) if isinstance(w, str) else np.nan
        # terminal label cross-check
        row["last_bid"] = g.bid.dropna().iloc[-1] if g.bid.notna().any() else np.nan
        rows.append(row)
    cap = pd.DataFrame(rows)
    cap.to_parquet(OUT / "capture.parquet", index=False)
    dec = cap[cap.resolved & cap.last_bid.notna() & ((cap.last_bid > .9) | (cap.last_bid < .1))]
    agree = (dec.won == (dec.last_bid > .9).astype(int)).mean() if len(dec) else float("nan")
    print(f"[capture] tokens with pre-start quotes: {len(cap)}; label-vs-terminal-price agreement: {agree:.3f} (n={len(dec)})")
    print(cap.groupby("cls").agg(n=("cid", "size"), resolved=("resolved", "sum")))

# ── stage: lever1 ───────────────────────────────────────────────────────────
def stage_lever1():
    from scipy.special import logit, expit
    from sklearn.isotonic import IsotonicRegression
    df = pd.read_parquet(OUT / "signals.parquet").dropna(subset=["v2_p", "entry", "won"]).copy()
    df["won"] = df.won.astype(int)
    df["mkt"] = df.entry.clip(.02, .98); df["v2"] = df.v2_p.clip(.02, .98)
    fit, ev = df[df.date < JULY], df[df.date >= JULY]
    print(f"[lever1] n fit={len(fit)} eval={len(ev)}")
    for nm, c in (("market", "mkt"), ("v2", "v2")):
        print(f"  {nm:7} Brier fit={_brier(fit[c], fit.won):.4f} eval={_brier(ev[c], ev.won):.4f}")
    def nll_k(k, d):
        p = expit(logit(d.mkt) + k * (logit(d.v2) - logit(d.mkt))).clip(1e-4, 1 - 1e-4)
        return -np.mean(d.won * np.log(p) + (1 - d.won) * np.log(1 - p))
    ks = np.linspace(-.5, 1.5, 81)
    k_hat = float(ks[int(np.argmin([nll_k(k, fit) for k in ks]))])
    for k in (0.0, 0.25, k_hat, 1.0):
        p = expit(logit(ev.mkt) + k * (logit(ev.v2) - logit(ev.mkt)))
        print(f"  logit-blend k={k:+.2f} eval Brier={_brier(p, ev.won):.4f}" + ("  (k fit on June)" if k == k_hat else ""))
    iso = IsotonicRegression(out_of_bounds="clip").fit(fit.v2, fit.won)
    print(f"  isotonic(June-fit) eval Brier={_brier(np.clip(iso.predict(ev.v2), .02, .98), ev.won):.4f}")
    rng = np.random.default_rng(7)
    def sim(d, p_adj, th, label):
        cost = (d.entry + 0.01).clip(upper=.99)
        b = d[(p_adj - cost) >= th]; c = cost[(p_adj - cost) >= th]
        if not len(b): print(f"  {label:30} th={th:.2f} n=0"); return
        pnl = np.where(b.won == 1, (1 - c) / c, -1.0)
        boots = np.array([rng.choice(pnl, len(pnl), replace=True).sum() for _ in range(4000)])
        print(f"  {label:30} th={th:.2f} n={len(b):3d} ROI={pnl.mean():+.1%} P(<=0)={np.mean(boots<=0):.3f}")
    sim(ev, ev.v2, 0.10, "raw v2 (current gate)")
    sim(ev, pd.Series(np.clip(iso.predict(ev.v2), .02, .98), index=ev.index), 0.05, "isotonic (June-frozen)")
    df["edge"] = df.v2 - df.mkt
    df["bucket"] = pd.cut(df.edge, [-1, -.1, -.05, 0, .05, .1, .2, 1])
    g = df.groupby("bucket", observed=True).agg(n=("won", "size"), wr=("won", "mean"), mkt=("mkt", "mean"), v2=("v2", "mean"))
    print("  dose-response (all GRID):"); print(g.round(3).to_string())

# ── stage: lever2 ───────────────────────────────────────────────────────────
def stage_lever2():
    df = pd.read_parquet(OUT / "signals.parquet").dropna(subset=["v2_p", "entry", "won"]).copy()
    df["won"] = df.won.astype(int); df["mkt"] = df.entry.clip(.02, .98); df["v2"] = df.v2_p.clip(.02, .98)
    fit, ev = df[df.date < JULY], df[df.date >= JULY]
    print("[lever2] v2-beats-market scan (Brier diff = market - v2; positive = v2 wins)")
    for g in ("cs2", "lol"):
        for floor in (0, 30, 75, 150):
            f_ = fit[(fit.game == g) & (fit.min_games >= floor)]; e_ = ev[(ev.game == g) & (ev.min_games >= floor)]
            if len(f_) < 8 or len(e_) < 8: continue
            print(f"  {g} games>={floor:3d}: fit n={len(f_):3d} d={_brier(f_.mkt, f_.won)-_brier(f_.v2, f_.won):+.4f}"
                  f" | eval n={len(e_):3d} d={_brier(e_.mkt, e_.won)-_brier(e_.v2, e_.won):+.4f}")
    c = df[df.game == "cs2"].copy(); c["tier"] = c.tier_ord.fillna(-1)
    print(c.groupby("tier").apply(lambda d: pd.Series(dict(n=len(d), mkt=_brier(d.mkt, d.won), v2=_brier(d.v2, d.won))), include_groups=False).round(4).to_string())

# ── stage: lever3 ───────────────────────────────────────────────────────────
def _sides_series():
    from sklearn.isotonic import IsotonicRegression
    cap = pd.read_parquet(OUT / "capture.parquet")
    ser = cap[(cap.cls == "series") & cap.resolved].copy()
    outmap = _outmap(); P = _predictors()
    sig = pd.read_parquet(OUT / "signals.parquet")
    logged = {(r.slug, str(r.outcome).lower()): r.v2_p for r in sig.itertuples(index=False) if pd.notna(r.v2_p)}
    rows = []
    for r in ser.itertuples(index=False):
        oth = next((o for o in (outmap.get(r.slug) or []) if isinstance(o, str)
                    and o.strip().lower() != str(r.outcome).strip().lower()), None)
        if oth is None: continue
        v2a = logged.get((r.slug, str(r.outcome).lower()))
        if v2a is None:
            pr = P[_game(r.slug)].predict(r.outcome, oth, at_time="2026-07-02")
            v2a = pr.get("model_prob_a") if pr.get("ok") else None
        if v2a is None: continue
        rows.append((r, oth, v2a))
    jun = sig[sig.date < JULY].dropna(subset=["v2_p", "won"])
    iso = IsotonicRegression(out_of_bounds="clip").fit(jun.v2_p.clip(.02, .98), jun.won.astype(int))
    sides = []
    for r, oth, v2a in rows:
        for side, team, p, cost, dep, won in (
                ("A", r.outcome, v2a, r.t5_ask, r.t5_adep, r.won),
                ("B", oth, 1 - v2a, (1 - r.t5_bid) if pd.notna(r.t5_bid) else np.nan, r.t5_bdep, 1 - r.won)):
            if pd.isna(cost): continue
            sides.append(dict(slug=r.slug, game=_game(r.slug), team=team, p=p,
                              p_iso=float(np.clip(iso.predict([min(max(p, .02), .98)])[0], .02, .98)),
                              cost=min(max(cost, .001), .999), dep=dep, won=won, gs_ts=r.gs_ts))
    return pd.DataFrame(sides)

def stage_lever3():
    S = _sides_series()
    S["pnl"] = np.where(S.won == 1, (1 - S.cost) / S.cost, -1.0)
    print(f"[lever3] fill-true sides: {len(S)} ({S.slug.nunique()} markets); every-side ROI={S.pnl.mean():+.1%} (window baseline!)")
    rng = np.random.default_rng(11)
    def run(pcol, th, label):
        b = S[((S[pcol] - S.cost) >= th) & (S.cost > .20) & (S.cost < .95) & (S.dep.fillna(0) >= 5)]
        if not len(b): print(f"  {label:30} th={th:.2f} n=0"); return
        pnl = np.where(b.won == 1, (1 - b.cost) / b.cost, -1.0)
        ex = []
        for r in b.itertuples(index=False):
            nb = S[(S.cost - r.cost).abs() <= .05]
            ex.append((1 - r.cost) / r.cost if r.won else -1.0)
            ex[-1] -= np.where(nb.won == 1, (1 - nb.cost) / nb.cost, -1.0).mean()
        ex = np.array(ex)
        boots = np.array([rng.choice(ex, len(ex), replace=True).mean() for _ in range(4000)])
        print(f"  {label:30} th={th:.2f} n={len(b):3d} ROI={pnl.mean():+.1%} "
              f"price-matched excess={ex.mean():+.3f}u P(excess<=0)={np.mean(boots<=0):.3f}")
    run("p", 0.10, "raw v2 vs captured ask")
    for th in (0.02, 0.05): run("p_iso", th, "isotonic (June-frozen)")

# ── stage: lever4 ───────────────────────────────────────────────────────────
def stage_lever4():
    cap = pd.read_parquet(OUT / "capture.parquet")
    d = cap[cap.resolved & (cap.cls != "series")].copy()
    d["match"] = d.slug.str.extract(r"^(.*?-\d{4}-\d{2}-\d{2})")[0].fillna(d.slug)
    sides = []
    for r in d.itertuples(index=False):
        if pd.notna(r.t5_ask) and 0 < r.t5_ask < 1:
            sides.append(dict(cls=r.cls, match=r.match, side="Y", cost=r.t5_ask, won=r.won))
        if pd.notna(r.t5_bid) and 0 < r.t5_bid < 1:
            sides.append(dict(cls=r.cls, match=r.match, side="N", cost=1 - r.t5_bid, won=1 - r.won))
    S = pd.DataFrame(sides)
    S = S[(S.cost >= .03) & (S.cost <= .97)]
    S["pnl"] = np.where(S.won == 1, (1 - S.cost) / S.cost, -1.0)
    print("[lever4] prop classes at executable quotes (Y=at ask, N=complement at 1-bid):")
    for (cls, side), g in S.groupby(["cls", "side"]):
        z = (g.won.sum() - g.cost.sum()) / math.sqrt((g.cost * (1 - g.cost)).sum())
        print(f"  {cls:11}{side} n={len(g):4d} ROI={g.pnl.mean():+.1%} z={z:+.2f}")

# ── stage: lever5 ───────────────────────────────────────────────────────────
def stage_lever5():
    d = pd.read_parquet(SNAP / "gamedata/inplay_joined.parquet")
    d["lp"] = np.where(d.a_won_map1, 1 - d.market_live, d.market_live)
    d["lw"] = np.where(d.a_won_map1, 1 - d.A_won, d.A_won).astype(int)
    print(f"[lever5] HISTORICAL join only (n={len(d)}, 2025-09..2026-01). "
          "Pre-registered gate requires laptop paper_results.csv -> run analysis/_inplay_sig.py there.")
    for lbl, dd in (("contrarian ALL", d), ("contrarian <=0.30", d[d.lp <= .3]), ("contrarian <=0.15", d[d.lp <= .15])):
        z = (dd.lw.sum() - dd.lp.sum()) / math.sqrt((dd.lp * (1 - dd.lp)).sum())
        print(f"  {lbl:20} n={len(dd):3d} z={z:+.2f} p={0.5*math.erfc(z/math.sqrt(2)):.4f}")

# ── stage: pnl ──────────────────────────────────────────────────────────────
def stage_pnl():
    lr = pd.read_csv(SNAP / "live/live_results.csv")
    lr["ts"] = pd.to_numeric(lr.ts, errors="coerce")
    lr["realized_pnl"] = pd.to_numeric(lr.realized_pnl, errors="coerce")
    g = lr[lr.ts >= GRID_T0]
    post = g[g.ts >= 1783017600]
    print(f"[pnl] GRID-era realized: ${g.realized_pnl.sum():+.2f} on {g.realized_pnl.notna().sum()} resolved fills; "
          f"post-v1.57: ${post.realized_pnl.sum():+.2f} on {post.realized_pnl.notna().sum()}")

STAGES = dict(signals=stage_signals, capture=stage_capture, lever1=stage_lever1,
              lever2=stage_lever2, lever3=stage_lever3, lever4=stage_lever4,
              lever5=stage_lever5, pnl=stage_pnl)
if __name__ == "__main__":
    want = sys.argv[1:] or list(STAGES)
    for s in want:
        STAGES[s]()
