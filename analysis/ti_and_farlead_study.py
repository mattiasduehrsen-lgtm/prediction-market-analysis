"""TI-2026 young-surface + far-lead calibration study — 2026-08-26.

The last two unmeasured data classes:

A) TI (Aug 13-23) Dota series books, captured end-to-end for the first time
   (v1.68 fixed the dota2- index hole 16 days before the event). Questions:
   is the young surface SOFT — wide spreads, thin depth, miscalibrated
   prices, beatable by the bo3 bookmaker line — or already sharp like CS2?

B) Far-lead series books (48h-120h pre-match), captured since v1.69
   (2026-08-03). Question: are far books miscalibrated enough at EXECUTABLE
   asks to clear the 10%*min(p,1-p) fee?

Method notes:
  - Capture rows log token A (outcomes[0]); bid/ask are for that side.
  - Resolutions from gamma by slug (cached; outcomePrices[0]=="1" -> side A won).
  - Fee = 0.10*min(p,1-p) on entry price p. All entries priced AT ASK.
  - Calibration reported in ask buckets; EV = mean(win - ask - fee).
  - bo3 join: winner rows matched by normalized team pair + date; bo3 covers
    CS2 (and some Dota via tier feeds) - coverage is reported, not assumed.

Run (laptop): .venv\\Scripts\\python.exe -u analysis\\ti_and_farlead_study.py
Artifacts: output/ti_study/{resolutions.json, report.txt}
"""
import glob
import json
import re
import sys
import time
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "analysis"))
from tape_backfill import _norm

CAP = ROOT / "output" / "price_capture"
ODDS = ROOT / "output" / "odds_capture"
OUT = ROOT / "output" / "ti_study"
OUT.mkdir(parents=True, exist_ok=True)
FEE = lambda p: 0.10 * min(p, 1.0 - p)
TI_LO = pd.Timestamp("2026-08-12", tz="UTC").timestamp()
TI_HI = pd.Timestamp("2026-08-25", tz="UTC").timestamp()
PROP_HINT = re.compile(r"-game\d|-map|handicap|total|kill|first|rampage|ultra|roshan|daytime|barra", re.I)


def load_series(prefixes, gs_lo=None, gs_hi=None):
    """cid -> {slug,g s_ts, ts[],bid[],ask[],ad[]} for series rows in capture."""
    books = {}
    for fp in sorted(glob.glob(str(CAP / "prices_*.jsonl"))):
        for line in open(fp, encoding="utf-8", errors="ignore"):
            if '"prop": 1' in line:
                continue
            ok = False
            for pref in prefixes:
                if f'"slug": "{pref}' in line:
                    ok = True; break
            if not ok:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            slug = e.get("slug", "")
            if PROP_HINT.search(slug) or e.get("bid") is None or e.get("ask") is None:
                continue
            gs = e.get("gs")
            if not gs:
                continue
            d = books.get(e["cid"])
            if d is None:
                try:
                    gs_ts = pd.Timestamp(gs).timestamp()
                except Exception:
                    continue
                if gs_lo and gs_ts < gs_lo:
                    continue
                if gs_hi and gs_ts >= gs_hi:
                    continue
                d = books.setdefault(e["cid"], {"slug": slug, "gs_ts": gs_ts,
                                                "ts": [], "bid": [], "ask": [], "ad": []})
            d["ts"].append(e["ts"]); d["bid"].append(e["bid"])
            d["ask"].append(e["ask"]); d["ad"].append(e.get("ask_depth") or 0.0)
    for d in books.values():
        o = np.argsort(d["ts"])
        for k in ("ts", "bid", "ask", "ad"):
            d[k] = np.asarray(d[k])[o]
    return books


def snap_at(d, t, tol=2700.0):
    """index of last snapshot <= t within tol, else None."""
    i = bisect_right(d["ts"], t) - 1
    if i < 0 or t - d["ts"][i] > tol:
        return None
    return i


def resolutions(slugs):
    cache_f = OUT / "resolutions.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    # drop entries from the pre-fix cache format / failed lookups
    cache = {k: v for k, v in cache.items() if isinstance(v, dict) and (v.get("w") is not None or v.get("out"))}
    S = requests.Session()
    todo = [s for s in slugs if s not in cache]
    for i, slug in enumerate(todo):
        try:
            # gamma's slug lookup EXCLUDES closed markets unless closed=true
            j = []
            for extra in ({"closed": "true"}, {}):
                r = S.get("https://gamma-api.polymarket.com/markets",
                          params={"slug": slug, **extra}, timeout=15)
                j = r.json()
                if isinstance(j, list) and j:
                    break
            if isinstance(j, list) and j:
                m = j[0]
                op = m.get("outcomePrices")
                op = json.loads(op) if isinstance(op, str) else op
                outs = m.get("outcomes")
                outs = json.loads(outs) if isinstance(outs, str) else (outs or [])
                w = (int(float(op[0]))
                     if m.get("closed") and op and float(op[0]) in (0.0, 1.0) else None)
                cache[slug] = {"w": w, "out": outs}
            else:
                cache[slug] = {"w": None, "out": []}
        except Exception:
            cache[slug] = {"w": None, "out": []}
        if i % 40 == 39:
            cache_f.write_text(json.dumps(cache))
            print(f"  [res] {i+1}/{len(todo)}")
        time.sleep(0.15)
    cache_f.write_text(json.dumps(cache))
    return cache


def softness(books, label, T_hours=(1, 6, 24)):
    print(f"\n[{label}] markets: {len(books)}")
    for T in T_hours:
        sp, dep = [], []
        for d in books.values():
            i = snap_at(d, d["gs_ts"] - T * 3600)
            if i is None:
                continue
            sp.append(d["ask"][i] - d["bid"][i]); dep.append(d["ad"][i])
        if sp:
            print(f"  T-{T:>2}h: n={len(sp):>4}  median spread {np.median(sp)*100:.1f}c  "
                  f"median ask-depth ${np.median(dep):.0f}")


def calib_ev(books, res, t_off_h, label, lo_h=None):
    """Buy side A at ask at T-minus; also inverted (side B at 1-bid). Report EV."""
    rows = []
    for cid, d in books.items():
        w = (res.get(d["slug"]) or {}).get("w")
        if w is None:
            continue
        t = d["gs_ts"] - t_off_h * 3600
        i = (snap_at(d, t) if lo_h is None else
             next((j for j in range(len(d["ts"]))
                   if d["gs_ts"] - lo_h * 3600 <= d["ts"][j] <= t), None))
        if i is None:
            continue
        a, b = d["ask"][i], d["bid"][i]
        if not (0.02 <= a <= 0.98) or b <= 0 or a - b > 0.25:
            continue
        rows.append((a, b, w, d["ad"][i], d["slug"]))
    if not rows:
        print(f"\n[{label}] n=0"); return
    A = np.array([(r[0], r[1], r[2]) for r in rows])
    evA = A[:, 2] - A[:, 0] - np.array([FEE(x) for x in A[:, 0]])
    askB = 1 - A[:, 1]
    evB = (1 - A[:, 2]) - askB - np.array([FEE(x) for x in askB])
    print(f"\n[{label}] n={len(rows)} resolved")
    print(f"  buy A at ask : EV {evA.mean()*100:+.1f}c/share (t={evA.mean()/ (evA.std()/np.sqrt(len(evA)) + 1e-9):.2f})")
    print(f"  buy B at ask : EV {evB.mean()*100:+.1f}c/share")
    for name, msk in (("fav (ask>.60)", A[:, 0] > .60), ("dog (ask<.40)", A[:, 0] < .40)):
        if msk.sum() >= 10:
            e = evA[msk]
            print(f"    {name:14} n={msk.sum():>3}  EV {e.mean()*100:+.1f}c  t={e.mean()/(e.std()/np.sqrt(len(e))+1e-9):.2f}")
    # calibration buckets
    print("  ask-bucket calibration (side A):")
    for lo in (0.05, 0.25, 0.45, 0.65, 0.85):
        m = (A[:, 0] >= lo) & (A[:, 0] < lo + 0.20)
        if m.sum() >= 8:
            print(f"    [{lo:.2f},{lo+0.2:.2f}) n={m.sum():>3}  mean ask {A[m,0].mean():.3f}  win rate {A[m,2].mean():.3f}")


def bo3_join(books, res):
    """Match bo3 winner lines to TI dota markets by team-pair + date."""
    # market side-A team from slug: dota2-<t1>-<t2>-YYYY-MM-DD
    mk = {}
    for cid, d in books.items():
        m = re.match(r"dota2-[a-z0-9]+-[a-z0-9]+-(\d{4})-(\d{2})-(\d{2})", d["slug"])
        outs = (res.get(d["slug"]) or {}).get("out") or []
        if m and len(outs) == 2:
            mk[cid] = (_norm(outs[0]), _norm(outs[1]),
                       f"{m.group(3)}-{m.group(2)}-{m.group(1)}")
    if not mk:
        print("\n[bo3] no parsable dota slugs"); return
    lines = {}
    for fp in sorted(glob.glob(str(ODDS / "odds_*.jsonl"))):
        day = fp[-13:-6]
        if not ("0812" <= day[3:] + day[:0] or True):
            pass
        for line in open(fp, encoding="utf-8", errors="ignore"):
            if '"kind": "winner"' not in line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            t1, t2 = _norm(e.get("team_1", "")), _norm(e.get("team_2", ""))
            dt = (e.get("start_date") or "")[:10]
            if not t1 or not t2 or not dt:
                continue
            dd = f"{dt[8:10]}-{dt[5:7]}-{dt[0:4]}"
            key = (t1, t2, dd)
            prev = lines.get(key)
            if prev is None or e["ts"] > prev["ts"]:
                lines[key] = {"ts": e["ts"], "imp1": e.get("imp_1"), "imp2": e.get("imp_2")}
    print(f"\n[bo3] winner-line match keys: {len(lines)}")
    hits = 0; evs = []
    for cid, (a1, a2, dd) in mk.items():
        d = books[cid]
        w = (res.get(d["slug"]) or {}).get("w")
        best = None
        for (t1, t2, ld), v in lines.items():
            if ld != dd:
                continue
            c = lambda x, y: len(x) >= 4 and len(y) >= 4 and (x in y or y in x)
            f1 = c(t1, a1) and c(t2, a2)
            f2 = c(t1, a2) and c(t2, a1)
            if f1 or f2:
                best = (v, f2); break
        if best is None:
            continue
        hits += 1
        if w is None:
            continue
        v, flipped = best
        impA = v["imp2"] if flipped else v["imp1"]
        if impA is None:
            continue
        i = snap_at(d, d["gs_ts"] - 1800, tol=5400)
        if i is None:
            continue
        a = d["ask"][i]
        if not (0.03 <= a <= 0.97):
            continue
        edge = impA - a - FEE(a)
        if edge >= 0.05:
            evs.append(w - a - FEE(a))
        edgeB = (1 - impA) - (1 - d["bid"][i]) - FEE(1 - d["bid"][i])
        if edgeB >= 0.05:
            evs.append((1 - w) - (1 - d["bid"][i]) - FEE(1 - d["bid"][i]))
    print(f"[bo3] dota markets matched to a bo3 line: {hits}/{len(mk)}")
    if evs:
        e = np.array(evs)
        print(f"[bo3] fill-true 'follow the book >=5c' bets: n={len(e)}  "
              f"EV {e.mean()*100:+.1f}c/share  sum {e.sum():+.2f} units")
    else:
        print("[bo3] no >=5c book-vs-market divergences at executable asks")


def main():
    print("=== A) TI DOTA SURFACE ===")
    dota = load_series(("dota2-",), TI_LO, TI_HI)
    cs2 = load_series(("cs2-", "csgo-"), TI_LO, TI_HI)
    softness(dota, "dota TI window")
    softness(cs2, "cs2 same window (baseline)")
    res = resolutions([d["slug"] for d in dota.values()])
    n_res = sum(1 for v in res.values() if isinstance(v, dict) and v.get("w") is not None)
    print(f"\n[res] resolved dota markets: {n_res}")
    calib_ev(dota, res, 0.5, "dota T-30min taker")
    calib_ev(dota, res, 6, "dota T-6h taker")
    bo3_join(dota, res)

    print("\n=== B) FAR-LEAD CALIBRATION (all titles, since v1.69) ===")
    allb = load_series(("cs2-", "csgo-", "lol-", "dota2-", "val-"),
                       pd.Timestamp("2026-08-05", tz="UTC").timestamp(), None)
    far_slugs = [d["slug"] for d in allb.values()
                 if snap_at(d, d["gs_ts"] - 48 * 3600, tol=86400) is not None]
    res2 = resolutions(far_slugs)
    far = {c: d for c, d in allb.items() if d["slug"] in set(far_slugs)}
    print(f"[far] markets with >=48h-lead quotes: {len(far)}")
    calib_ev(far, res2, 48, "far T-48h..120h taker", lo_h=120)
    calib_ev(far, res2, 1, "same markets at T-1h (sharpness reference)")


if __name__ == "__main__":
    main()
