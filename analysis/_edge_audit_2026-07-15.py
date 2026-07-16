"""Consolidated reproduction — EDGE AUDIT 2026-07-15 (see COWORK_EDGE_AUDIT_2026-07-15.md).

Runs entirely on cowork_snapshot/. Stages (run all, or pass stage names as argv):
  build       consolidate live/price_capture/*.jsonl -> output/edge_audit/capture_all.parquet
  settlement  settlement-lag rule sim + reversal risk        (verdict: DEAD)
  ladder      totals-ladder monotonicity arb scan            (verdict: DEAD)
  calib       pre-start calibration + steam test + GRID rpt  (verdict: no taker edge)
  maker       wallet-level maker/taker PnL, Mar29-Apr14 tape (verdict: naive making toxic)
"""
from __future__ import annotations
import json, glob, os, re, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "cowork_snapshot"
OUT = ROOT / "output" / "edge_audit"
OUT.mkdir(parents=True, exist_ok=True)
CAP = OUT / "capture_all.parquet"


def load_res():
    r = pd.read_parquet(SNAP / "esports/resolutions.parquet")
    return r[r.resolved & r.winning_outcome.notna()]


# ---------------------------------------------------------------- build
def build():
    rows = {k: [] for k in ("ts", "cid", "slug", "outcome", "prop", "gs", "bid", "ask", "bd", "ad")}
    for fp in sorted(glob.glob(str(SNAP / "live/price_capture/prices_*.jsonl"))):
        with open(fp) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                rows["ts"].append(d.get("ts") or np.nan)
                rows["cid"].append(d.get("cid") or "")
                rows["slug"].append(d.get("slug") or "")
                rows["outcome"].append(d.get("outcome") or "")
                rows["prop"].append(d.get("prop") or 0)
                rows["gs"].append(d.get("gs") or "")
                rows["bid"].append(np.nan if d.get("bid") is None else d["bid"])
                rows["ask"].append(np.nan if d.get("ask") is None else d["ask"])
                rows["bd"].append(d.get("bid_depth") or 0.0)
                rows["ad"].append(d.get("ask_depth") or 0.0)
        print("read", os.path.basename(fp), len(rows["ts"]), flush=True)
    df = pd.DataFrame({
        "ts": np.asarray(rows["ts"], "float64"), "cid": pd.Categorical(rows["cid"]),
        "slug": pd.Categorical(rows["slug"]), "outcome": pd.Categorical(rows["outcome"]),
        "prop": np.asarray(rows["prop"], "int8"), "gs": pd.Categorical(rows["gs"]),
        "bid": np.asarray(rows["bid"], "float32"), "ask": np.asarray(rows["ask"], "float32"),
        "bid_depth": np.asarray(rows["bd"], "float32"), "ask_depth": np.asarray(rows["ad"], "float32")})
    df.to_parquet(CAP, index=False)
    print("saved", CAP, len(df), "rows,", df.cid.nunique(), "markets")


# ---------------------------------------------------------------- settlement
def settlement():
    cap = pd.read_parquet(CAP)
    res = load_res()
    res_map = dict(zip(res.condition_id, res.winning_outcome))
    cap = cap[cap.cid.isin(res_map.keys())].copy()
    cap["win"] = cap.cid.map(res_map).astype(str)
    w = (cap.outcome.astype(str) == cap.win).values
    cap["w_bid"] = np.where(w, cap.bid, 1.0 - cap.ask)
    cap["w_ask"] = np.where(w, cap.ask, 1.0 - cap.bid)
    cap["l_bid"] = np.where(w, 1.0 - cap.ask, cap.bid)
    cap["l_ask"] = np.where(w, 1.0 - cap.bid, cap.ask)
    cap = cap.sort_values(["cid", "ts"])
    g = cap.groupby("cid", observed=True).agg(max_w=("w_bid", "max"), max_l=("l_bid", "max"))
    for trig in (0.95, 0.97, 0.98, 0.99):
        wl, ll = (g.max_w >= trig).sum(), (g.max_l >= trig).sum()
        print(f"bid>={trig}: winner hit {wl}, LOSER hit {ll} -> market-level reversal "
              f"{ll/max(wl+ll,1):.4f}")
    for trig, amax in ((0.97, 0.99), (0.98, 0.995)):
        n = losses = 0
        cost = pnl = 0.0
        for cid, d in cap.groupby("cid", observed=True):
            hw, hl = d.w_bid.values >= trig, d.l_bid.values >= trig
            ha = hw | hl
            if not ha.any():
                continue
            i = int(np.argmax(ha))
            r = d.iloc[i]
            is_w = bool(hw[i])
            ask = r.w_ask if is_w else r.l_ask
            if not np.isfinite(ask) or ask > amax or ask <= trig - 0.05:
                continue
            n += 1
            cost += ask
            pnl += (1 - ask) if is_w else -ask
            losses += 0 if is_w else 1
        print(f"RULE trig={trig} amax={amax}: n={n} losses={losses} ROI={pnl/max(cost,1e-9)*100:+.2f}%")
    print("VERDICT: DEAD — asks <= 0.99 while 'decided' are adversely selected (mid-match comebacks).")


# ---------------------------------------------------------------- ladder
def ladder():
    cap = pd.read_parquet(CAP)
    cap = cap[cap.prop == 1].copy()
    u = pd.Series(cap.slug.cat.categories.astype(str))
    ex = u.str.extract(r"^(?P<root>.+?)-(?P<kind>round-total|total-maps|kills?-total|total)-(?P<k>\d+)pt5$")
    ex["slug"] = u
    ex = ex.dropna(subset=["root", "k"])
    ex["k"] = ex.k.astype(int)
    lm = ex.set_index("slug")
    cap["slug_s"] = cap.slug.astype(str)
    cap = cap[cap.slug_s.isin(lm.index)]
    cap = cap[cap.outcome.astype(str) == "Over"].copy()
    cap["root"] = cap.slug_s.map(lm.root)
    cap["kind"] = cap.slug_s.map(lm.kind)
    cap["k"] = cap.slug_s.map(lm.k).astype(int)
    cap["bucket"] = (cap.ts // 60).astype("int64")
    q = (cap.sort_values("ts").groupby(["root", "kind", "bucket", "k"], observed=True)
         .agg(bid=("bid", "last"), ask=("ask", "last"), bd=("bid_depth", "last"),
              ad=("ask_depth", "last")).reset_index()
         .sort_values(["root", "kind", "bucket", "k"], kind="mergesort").reset_index(drop=True))
    nxt = (q.root == q.root.shift(-1)) & (q.kind == q.kind.shift(-1)) & (q.bucket == q.bucket.shift(-1))
    lo, hi = q[nxt.values].reset_index(drop=True), q.shift(-1)[nxt.values].reset_index(drop=True)
    m = np.isfinite(lo.ask.values) & np.isfinite(hi.bid.values)
    gap = hi.bid.values - lo.ask.values
    v = m & (gap > 1e-9)
    print(f"adjacent-strike pair-buckets with two-sided quotes: {m.sum():,}; violations: {v.sum()}")
    if v.any():
        prof = gap[v] * np.minimum(lo.ad.values[v], hi.bd.values[v])
        print(f"total instantaneous capturable over window: ${prof.sum():.2f}")
    print("VERDICT: DEAD — books are one-sided; the prop MM never quotes an incoherent ladder.")


# ---------------------------------------------------------------- calib
def calib():
    res = load_res()
    win = set(res.winning_token.astype(str))
    rc = set(res.condition_id)
    mk = pd.read_parquet(SNAP / "esports/clob_esports_markets.parquet",
                         columns=["condition_id", "game_start"])
    gsm = dict(zip(mk.condition_id, pd.to_datetime(mk.game_start, errors="coerce", utc=True)))
    fr = [pd.read_parquet(SNAP / f"esports/esports_trades_part{i}.parquet",
                          columns=["timestamp", "token_id", "price", "condition_id", "slug"])
          for i in (2, 3)]
    t = pd.concat(fr)
    t = t[t.condition_id.isin(rc)].copy()
    t["gs"] = t.condition_id.map(gsm)
    t = t[t.gs.notna()]
    t["gs_ts"] = t.gs.astype("int64") / 1e9
    pre = t[t.timestamp < t.gs_ts - 300]
    last = (pre.sort_values("timestamp").groupby(["condition_id", "token_id"])
            .agg(p=("price", "last"), ts=("timestamp", "last"), gs=("gs_ts", "last"),
                 n=("price", "size")).reset_index())
    last["won"] = last.token_id.astype(str).isin(win).astype(int)
    fresh = last[(last.n >= 10) & ((last.gs - last.ts) < 1800)]
    d = fresh[fresh.p.between(0.2, 0.8)]
    print(f"FRESH mid-band (0.2-0.8) calibration: n={len(d)}, edge={(d.won.mean()-d.p.mean()):+.4f}")
    for lo, hi in ((0.0, 0.1), (0.9, 1.0)):
        dd = fresh[fresh.p.between(lo, hi)]
        if len(dd):
            print(f"FRESH tail {lo}-{hi}: n={len(dd)}, p={dd.p.mean():.3f}, actual={dd.won.mean():.3f}")
    # steam
    wm = t[~t.slug.str.contains("total|handicap|kills", na=False)]
    early = wm[(wm.timestamp < wm.gs_ts - 3600) & (wm.timestamp > wm.gs_ts - 6 * 3600)]
    late = wm[(wm.timestamp > wm.gs_ts - 900) & (wm.timestamp < wm.gs_ts - 60)]
    e = early.sort_values("timestamp").groupby(["condition_id", "token_id"]).price.last()
    l = late.sort_values("timestamp").groupby(["condition_id", "token_id"]).price.last()
    j = pd.concat([e.rename("pe"), l.rename("pl")], axis=1).dropna().reset_index()
    j["won"] = j.token_id.astype(str).isin(win).astype(int)
    j["drift"] = j.pl - j.pe
    j = j[j.pl.between(0.10, 0.90)]
    for lo, hi in ((0.02, 0.05), (0.05, 0.10)):
        for sgn in (1, -1):
            d = j[(sgn * j.drift).between(lo, hi)]
            if len(d) > 30:
                ed = d.won - d.pl
                print(f"steam {'+' if sgn>0 else '-'}[{lo},{hi}): n={len(d)} "
                      f"edge_vs_late={ed.mean():+.4f} z={ed.mean()/(ed.std()/np.sqrt(len(d))):+.2f}")
    tm = pd.read_parquet(SNAP / "study/tape_backfill/tape_marks.parquet")
    tm = tm[tm.resolved & tm.t1_vwap.notna()]
    e2 = tm.a_won - tm.t1_vwap
    print(f"GRID-era T-1 calibration: n={len(tm)}, edge={e2.mean():+.4f}, "
          f"z={e2.mean()/(e2.std()/np.sqrt(len(e2))):+.2f}")
    print("VERDICT: market calibrated everywhere it trades; steam dead; no band-buy edge.")


# ---------------------------------------------------------------- maker
def maker():
    res = load_res()
    win = set(res.winning_token.astype(str))
    rc = set(res.condition_id)
    fr = [pd.read_parquet(SNAP / f"esports/esports_trades_part{i}.parquet",
                          columns=["timestamp", "token_id", "side", "price", "size",
                                   "maker", "taker", "condition_id", "slug"]) for i in (2, 3)]
    t = pd.concat(fr, ignore_index=True)
    dre = re.compile(r"(\d{4}-\d{2}-\d{2})")
    sd = {s: (m.group(1) if (m := dre.search(s)) else None) for s in t.slug.unique()}
    t["md"] = t.slug.map(sd)
    t = t[t.condition_id.isin(rc) & t.md.notna()]
    t = t[(t.md >= "2026-03-29") & (t.md <= "2026-04-14")].copy()
    t["notional"] = t.price * t["size"]
    buy = (t.side == "BUY").values
    tr = pd.DataFrame({"wallet": t.taker.values, "token": t.token_id.values,
                       "ds": np.where(buy, t["size"].values, -t["size"].values),
                       "dc": np.where(buy, -t.notional.values, t.notional.values),
                       "no": t.notional.values, "mk": 0})
    mr = pd.DataFrame({"wallet": t.maker.values, "token": t.token_id.values,
                       "ds": np.where(buy, -t["size"].values, t["size"].values),
                       "dc": np.where(buy, t.notional.values, -t.notional.values),
                       "no": t.notional.values, "mk": 1})
    p = pd.concat([tr, mr], ignore_index=True)
    tok = p.groupby(["wallet", "token"], sort=False).ds.sum().reset_index()
    tok["term"] = tok.ds * tok.token.astype(str).isin(win).astype(int)
    term = tok.groupby("wallet").term.sum()
    w = p.groupby("wallet").agg(cash=("dc", "sum"), no=("no", "sum"))
    w["mno"] = p[p.mk == 1].groupby("wallet").no.sum().reindex(w.index).fillna(0)
    w["pnl"] = w.cash + term.reindex(w.index).fillna(0)
    w["mf"] = w.mno / w.no
    big = w[w.no >= 5000]
    for name, seg in (("PURE MAKER (mf>=0.9)", big[big.mf >= 0.9]),
                      ("MOSTLY MAKER (0.6-0.9)", big[(big.mf >= 0.6) & (big.mf < 0.9)]),
                      ("MIXED (0.4-0.6)", big[(big.mf >= 0.4) & (big.mf < 0.6)]),
                      ("PURE TAKER (<0.1)", big[big.mf < 0.1])):
        print(f"{name}: n={len(seg)}, pnl ${seg.pnl.sum():,.0f} on ${seg.no.sum():,.0f} "
              f"({seg.pnl.sum()/max(seg.no.sum(),1)*100:+.2f}%)")
    print("VERDICT: naive resting liquidity was NET NEGATIVE pre-GRID (informed/latency flow "
          "picked makers off). Making only works with a fair-value anchor + fast cancels — "
          "which is what the updown maker plan must prove in Phase 1.")


STAGES = {"build": build, "settlement": settlement, "ladder": ladder,
          "calib": calib, "maker": maker}

if __name__ == "__main__":
    names = sys.argv[1:] or list(STAGES)
    for n in names:
        print(f"\n{'='*70}\nSTAGE {n}\n{'='*70}")
        STAGES[n]()
