"""GRID-era trade-tape backfill — enlarge the R1 evidence base (2026-07-06).

The capture logger (fill-true referee) only started 2026-07-01, but every
Polymarket fill since the GRID transition (2026-06-23) exists in the data-api.
This backfills the tape for ALL GRID-era esports series markets, computes
pre-start traded-price marks (T-15/T-5/T-1), joins resolutions + v2 probs, and
re-scores the frozen R1 curve on the enlarged population.

EVIDENCE-HARDENING ONLY. Nothing here may touch the pre-registered R1 triggers:
a great result still waits for the paper stream; a terrible one has its own
KILL trigger. Tape prices are FILLS, not quotes — costs below use last-trade
+1c as an ask proxy and are labeled "tape-priced" to keep them distinct from
the capture-based fill-true numbers.

v2-prob hygiene: live-logged probs (fade_events) are the clean subset. Rows
priced by the LOCAL predictor are flagged leak_prone=1 — the local model state
postdates the matches, so its Elo/GBM features have seen the outcomes.

Stages: fetch marks report        (default: all)
Run:    .venv\\Scripts\\python.exe -u analysis/tape_backfill.py [stage ...]
Output: output/tape_backfill/trades/*.parquet (per-market tape, resumable)
        output/tape_backfill/tape_marks.parquet + printed report
"""
import json, math, re, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from esports_fade_bot import is_single_map_market, r1_calibrate  # single source of truth

OUT = ROOT / "output" / "tape_backfill"
TR = OUT / "trades"
TR.mkdir(parents=True, exist_ok=True)
MK = ROOT / "cowork_snapshot" / "esports" / "clob_esports_markets.parquet"
RES = ROOT / "cowork_snapshot" / "esports" / "resolutions.parquet"
SIGNALS = ROOT / "output" / "grid_refit" / "signals.parquet"   # _grid_refit_2026-07-05.py signals
TIER = ROOT / "cowork_snapshot" / "gamedata" / "bo3" / "tier_index.parquet"

API = "https://data-api.polymarket.com/trades"
GRID_T0 = pd.Timestamp("2026-06-23", tz="UTC")
S = requests.Session()


def _game(slug):
    s = (slug or "").lower()
    if "vct" in s or "valorant" in s:
        return None
    if s.startswith(("lol-", "arch-lol-", "league-")):
        return "lol"
    if s.startswith(("cs2-", "csgo-")):
        return "cs2"
    # CoD (v1.64, CDL listings began Jul 2026; slug form "chi1-csc-cdl-<date>").
    # No v2 predictor exists for cod — marks fall back to market-only rows.
    if "-cdl-" in s or s.startswith(("cdl-", "cod-")):
        return "cod"
    return None


def universe():
    df = pd.read_parquet(MK, columns=["condition_id", "slug", "tokens", "game_start"])
    df["game"] = df.slug.map(_game)
    gs = pd.to_datetime(df.game_start, errors="coerce", utc=True)
    m = df[df.game.notna() & gs.notna() & (gs >= GRID_T0)
           & (gs <= pd.Timestamp.utcnow())
           & ~df.slug.map(is_single_map_market)].copy()
    m["gs"] = gs[m.index]

    def outs(t):
        try:
            return [x.get("outcome") for x in (json.loads(t) if isinstance(t, str) else list(t))
                    if isinstance(x.get("outcome"), str)]
        except Exception:
            return []
    m["outcomes"] = m.tokens.map(outs)
    m = m[m.outcomes.map(len) == 2].drop(columns=["tokens"])
    return m.drop_duplicates("condition_id")


def stage_fetch():
    uni = universe()
    print(f"[fetch] GRID-era series universe: {len(uni)} markets "
          f"(cs2={int((uni.game == 'cs2').sum())}, lol={int((uni.game == 'lol').sum())})")
    todo = [r for r in uni.itertuples(index=False)
            if not (TR / f"{r.condition_id}.parquet").exists()]
    print(f"[fetch] to download: {len(todo)} (rest cached)")
    for i, r in enumerate(todo, 1):
        rows, offset = [], 0
        while True:
            try:
                resp = S.get(API, params={"market": r.condition_id, "limit": 500,
                                          "offset": offset}, timeout=20)
            except Exception as e:
                print(f"  net error {r.slug[:40]}: {e}; retry in 3s"); time.sleep(3); continue
            if resp.status_code == 429:
                time.sleep(10); continue
            if resp.status_code != 200:
                break
            page = resp.json()
            if not page:
                break
            rows.extend({"ts": t.get("timestamp"), "price": t.get("price"),
                         "size": t.get("size"), "side": t.get("side"),
                         "outcome": t.get("outcome"),
                         # wallet added 2026-07-13 for the wallet-skill study —
                         # caches created before then lack this column
                         "wallet": t.get("proxyWallet")} for t in page)
            if len(page) < 500:
                break
            offset += 500
            time.sleep(0.15)
        pd.DataFrame(rows).to_parquet(TR / f"{r.condition_id}.parquet", index=False)
        if i % 25 == 0:
            print(f"  {i}/{len(todo)} markets fetched")
        time.sleep(0.1)
    print("[fetch] done")


# pre-start windows in minutes before game_start (same as the GRID re-fit)
WINDOWS = (("t15", 12, 25), ("t5", 3, 8), ("t1", 0, 3))


def stage_marks():
    uni = universe()
    res = pd.read_parquet(RES)
    res = res[res.winning_outcome.notna()][["slug", "winning_outcome"]].drop_duplicates("slug")
    win = dict(zip(res.slug, res.winning_outcome))

    logged = {}
    if SIGNALS.exists():
        sig = pd.read_parquet(SIGNALS)
        logged = {(r.slug, str(r.outcome).strip().lower()): r.v2_p
                  for r in sig.itertuples(index=False) if pd.notna(r.v2_p)}
    else:
        print("[marks] WARNING: signals.parquet missing — run _grid_refit signals first")

    preds = {}
    try:
        sys.path.insert(0, str(ROOT / "esports_model" / "src"))
        from predict import Predictor
        preds = {g: Predictor(g) for g in ("cs2", "lol")}
    except Exception as e:
        print(f"[marks] local predictor unavailable ({e}) — live-logged probs only")

    rows, n_tape = [], 0
    for r in uni.itertuples(index=False):
        fp = TR / f"{r.condition_id}.parquet"
        if not fp.exists():
            continue
        t = pd.read_parquet(fp)
        if t.empty:
            continue
        n_tape += 1
        for c in ("ts", "price", "size"):
            t[c] = pd.to_numeric(t[c], errors="coerce")
        t = t.dropna(subset=["ts", "price"])
        a, b = r.outcomes
        # normalize every fill to outcome-A price
        t["pa"] = np.where(t.outcome.astype(str).str.strip().str.lower()
                           == str(a).strip().lower(), t.price, 1 - t.price)
        t["tmin"] = (r.gs.value / 1e9 - t.ts) / 60.0
        row = dict(cid=r.condition_id, slug=r.slug, game=r.game, team_a=a, team_b=b,
                   gs=r.gs, n_trades=len(t),
                   n_prestart=int(((t.tmin >= 0) & (t.tmin <= 90)).sum()))
        for mark, lo, hi in WINDOWS:
            w = t[(t.tmin >= lo) & (t.tmin <= hi)].sort_values("ts")
            if len(w):
                row[f"{mark}_pa"] = float(w.pa.iloc[-1])
                row[f"{mark}_vwap"] = float((w.pa * w["size"]).sum() / w["size"].sum())
                row[f"{mark}_n"] = int(len(w))
        wn = win.get(r.slug)
        row["resolved"] = isinstance(wn, str)
        row["a_won"] = (int(str(wn).strip().lower() == str(a).strip().lower())
                        if isinstance(wn, str) else np.nan)
        # v2 prob for A: live-logged first (clean), local predictor second (leak-prone)
        v2a, leak = None, 0
        for team, flip in ((a, False), (b, True)):
            lv = logged.get((r.slug, str(team).strip().lower()))
            if lv is not None:
                v2a = float(1 - lv) if flip else float(lv)
                break
        if v2a is None and r.game in preds:
            try:
                pr = preds[r.game].predict(a, b, at_time=str(r.gs.date()))
                if pr.get("ok"):
                    v2a, leak = float(pr["model_prob_a"]), 1
            except Exception:
                pass
        row["v2_pa"] = v2a
        row["leak_prone"] = leak
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_parquet(OUT / "tape_marks.parquet", index=False)
    print(f"[marks] markets with tape: {n_tape}; with t5 mark: {int(df.t5_pa.notna().sum())}; "
          f"resolved: {int(df.resolved.sum())}; v2 priced: {int(df.v2_pa.notna().sum())} "
          f"(live-logged {int((df.v2_pa.notna() & (df.leak_prone == 0)).sum())}, "
          f"local/leak-prone {int((df.leak_prone == 1).sum())})")


def _tier_map():
    if not TIER.exists():
        return {}
    tier = pd.read_parquet(TIER)
    tmap = {}
    for r in tier.itertuples(index=False):
        tmap[(r.a, r.b, r.date)] = int(r.tier_ord)
    return tmap


def _norm(s):
    if not isinstance(s, str):
        return ""
    # v1.61: keep in sync with build_tier_index.norm (csgo/cs2 suffix strip)
    s = re.sub(r"\b(esports|esport|e sports|gaming|team|clan|club|gg|cs[ -]?go|cs ?2)\b",
               " ", s.lower())
    return re.sub(r"[^a-z0-9]", "", s)


def _tier_for(tmap, a, b, gs):
    na, nb = _norm(a), _norm(b)
    k0, k1 = min(na, nb), max(na, nb)
    for dd in (0, 1, -1):
        t = tmap.get((k0, k1, (gs + pd.Timedelta(days=dd)).strftime("%Y-%m-%d")))
        if t is not None:
            return t
    return None


def _brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def stage_report():
    df = pd.read_parquet(OUT / "tape_marks.parquet")
    d = df[df.resolved & df.t5_pa.notna() & df.v2_pa.notna()].copy()
    d["a_won"] = d.a_won.astype(int)
    tmap = _tier_map()
    d["tier_ord"] = [_tier_for(tmap, a, b, gs) if g == "cs2" else None
                     for a, b, g, gs in zip(d.team_a, d.team_b, d.game, d.gs)]

    # two sides per market, tape cost = last pre-start fill +1c (ask PROXY, not a quote)
    sides = []
    for r in d.itertuples(index=False):
        for team, p_mkt, v2, won in ((r.team_a, r.t5_pa, r.v2_pa, r.a_won),
                                     (r.team_b, 1 - r.t5_pa, 1 - r.v2_pa, 1 - r.a_won)):
            sides.append(dict(slug=r.slug, game=r.game, team=team, mkt=p_mkt, v2=v2,
                              p_r1=r1_calibrate(min(max(v2, 0.0), 1.0)), won=won,
                              cost=min(p_mkt + 0.01, 0.99), leak=r.leak_prone,
                              tier_ord=r.tier_ord,
                              match=re.sub(r"-game\d+$", "", r.slug)))
    S_ = pd.DataFrame(sides)
    S_ = S_[(S_.mkt > 0.01) & (S_.mkt < 0.99)]

    print(f"\n[report] GRID-era tape population: {d.slug.nunique()} resolved series markets, "
          f"{len(S_)} sides (vs 188 signals in the re-fit)")
    for label, sub in (("clean (live-logged v2)", S_[S_.leak == 0]),
                       ("leak-prone (local v2)", S_[S_.leak == 1]),
                       ("ALL", S_)):
        if len(sub) < 8:
            print(f"  {label:26} n={len(sub)} (too small)"); continue
        print(f"  {label:26} n={len(sub):4d}  Brier: market={_brier(sub.mkt.clip(.02, .98), sub.won):.4f} "
              f"v2={_brier(sub.v2.clip(.02, .98), sub.won):.4f} "
              f"p_r1={_brier(sub.p_r1.clip(.02, .98), sub.won):.4f}")

    # R1 gate sim at tape costs (+1c proxy) — price-matched excess, cluster bootstrap
    rng = np.random.default_rng(7)

    def sim(sub, label, tier_rule):
        b = sub[(sub.p_r1 - sub.cost >= 0.05) & (sub.cost > 0.20) & (sub.cost < 0.95)
                & (sub.game == "cs2")]
        if tier_rule:
            b = b[b.tier_ord.notna() & (b.tier_ord < 4)]
        b = b.sort_values("slug").drop_duplicates("match")   # 1 entry per match
        if not len(b):
            print(f"  {label:44} n=0"); return
        pnl = np.where(b.won == 1, (1 - b.cost) / b.cost, -1.0)
        ex = []
        for r in b.itertuples(index=False):
            base = sub[(sub.cost - r.cost).abs() <= 0.05]
            own = (1 - r.cost) / r.cost if r.won else -1.0
            ex.append(own - np.where(base.won == 1, (1 - base.cost) / base.cost, -1.0).mean())
        ex = np.array(ex)
        by_match = pd.DataFrame({"m": b.match.values, "ex": ex}).groupby("m").ex.mean()
        boots = np.array([rng.choice(by_match, len(by_match), replace=True).mean()
                          for _ in range(4000)])
        print(f"  {label:44} n={len(b):3d} ROI={pnl.mean():+.1%} "
              f"excess={ex.mean():+.3f}u P(excess<=0)={np.mean(boots <= 0):.3f}")

    print("\n  R1 gate @ tape cost (+1c ask PROXY — weaker than captured asks):")
    sim(S_[S_.leak == 0], "clean, no tier filter", False)
    sim(S_[S_.leak == 0], "clean, tier known & non-S", True)
    sim(S_, "ALL (incl leak-prone), no tier filter", False)
    sim(S_, "ALL, tier known & non-S", True)

    # frozen-curve robustness: isotonic refit on the enlarged population (REPORT ONLY)
    try:
        from sklearn.isotonic import IsotonicRegression
        for label, sub in (("clean", S_[S_.leak == 0]), ("ALL", S_)):
            if len(sub) < 50:
                continue
            iso = IsotonicRegression(out_of_bounds="clip").fit(
                sub.v2.clip(.02, .98), sub.won)
            xs = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.65, 0.70, 0.80, 0.85, 0.90]
            fr = [r1_calibrate(x) for x in xs]
            rf = [float(iso.predict([x])[0]) for x in xs]
            dmax = max(abs(f - g) for f, g in zip(fr, rf))
            print(f"\n  curve robustness ({label}, n={len(sub)}): max|frozen - refit| = {dmax:.3f}")
            print("    x     : " + " ".join(f"{x:.2f}" for x in xs))
            print("    frozen: " + " ".join(f"{v:.2f}" for v in fr))
            print("    refit : " + " ".join(f"{v:.2f}" for v in rf))
        print("  (refit curves are DIAGNOSTIC ONLY — the trading curve stays frozen;"
              " adopting a refit = new pre-registration, clock restarts)")
    except Exception as e:
        print(f"  curve refit skipped ({e})")


STAGES = dict(fetch=stage_fetch, marks=stage_marks, report=stage_report)
if __name__ == "__main__":
    for s in (sys.argv[1:] or list(STAGES)):
        STAGES[s]()
