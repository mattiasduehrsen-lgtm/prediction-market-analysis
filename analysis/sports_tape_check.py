"""Sports-fade fill-true check — price the paper claims at the real tape (2026-07-09).

The sports paper bot logs fades at ENTRY prices (1 - their_price), the same
accounting that flattered esports paper (+7% paper -> negative live, May MLB).
This fetches the actual Polymarket trade tape for recent WTA/MLB markets and
re-prices every paper signal at the FIRST REAL FILL on our outcome within 10
minutes of the signal (+1c), keeping resolution labels from the evaluator.

Claimed-vs-tape gap = execution mirage. Clustered stats by market (trades on
the same match share one outcome; per-trade t-stats overstate).

Run: .venv\\Scripts\\python.exe -u analysis/sports_tape_check.py [fetch score]
Input: output/sports_check/paper_results.csv (copied from laptop)
"""
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "sports_check"
TR = OUT / "trades"
TR.mkdir(parents=True, exist_ok=True)
API = "https://data-api.polymarket.com/trades"
SINCE = "2026-06-18"
SPORTS = ("wta-", "mlb-")
FILL_WINDOW_S = 600
S = requests.Session()


def load_signals():
    df = pd.read_csv(OUT / "paper_results.csv")
    df["ts"] = pd.to_numeric(df.timestamp, errors="coerce")
    df["date"] = pd.to_datetime(df.ts, unit="s", utc=True).dt.strftime("%Y-%m-%d")
    df = df[df.realized_pnl.notna() & (df.date >= SINCE)
            & df.fade_slug.str.startswith(SPORTS, na=False)].copy()
    df["sport"] = df.fade_slug.str.split("-").str[0]
    return df


def stage_fetch():
    df = load_signals()
    cids = df.drop_duplicates("fade_condition")[["fade_condition", "fade_slug"]]
    todo = [r for r in cids.itertuples(index=False)
            if not (TR / f"{r.fade_condition}.parquet").exists()]
    print(f"[fetch] markets: {len(cids)} (wta={df[df.sport=='wta'].fade_condition.nunique()}, "
          f"mlb={df[df.sport=='mlb'].fade_condition.nunique()}); to download: {len(todo)}")
    for i, r in enumerate(todo, 1):
        rows, offset = [], 0
        while True:
            try:
                resp = S.get(API, params={"market": r.fade_condition, "limit": 500,
                                          "offset": offset}, timeout=20)
            except Exception:
                time.sleep(3); continue
            if resp.status_code == 429:
                time.sleep(10); continue
            if resp.status_code != 200:
                break
            page = resp.json()
            if not page:
                break
            rows.extend({"ts": t.get("timestamp"), "price": t.get("price"),
                         "size": t.get("size"), "outcome": t.get("outcome")}
                        for t in page)
            if len(page) < 500:
                break
            offset += 500
            time.sleep(0.15)
        pd.DataFrame(rows).to_parquet(TR / f"{r.fade_condition}.parquet", index=False)
        if i % 50 == 0:
            print(f"  {i}/{len(todo)}")
        time.sleep(0.1)
    print("[fetch] done")


def stage_score():
    df = load_signals()
    rows, no_tape, no_fill = [], 0, 0
    for r in df.itertuples(index=False):
        fp = TR / f"{r.fade_condition}.parquet"
        if not fp.exists():
            no_tape += 1; continue
        t = pd.read_parquet(fp)
        if t.empty:
            no_tape += 1; continue
        t["ts"] = pd.to_numeric(t.ts, errors="coerce")
        t["price"] = pd.to_numeric(t.price, errors="coerce")
        ours = t[(t.outcome.astype(str).str.strip().str.lower()
                  == str(r.our_outcome).strip().lower())
                 & (t.ts >= r.ts) & (t.ts <= r.ts + FILL_WINDOW_S)].sort_values("ts")
        if ours.empty:
            no_fill += 1; continue
        cost = min(float(ours.price.iloc[0]) + 0.01, 0.99)
        won = int(str(r.winning_outcome).strip().lower()
                  == str(r.our_outcome).strip().lower())
        rows.append(dict(sport=r.sport, market=r.fade_slug, ts=r.ts,
                         entry=float(r.our_entry), cost=cost, won=won))
    d = pd.DataFrame(rows)
    d.to_parquet(OUT / "tape_scored.parquet", index=False)
    print(f"[score] scored {len(d)}; no tape {no_tape}; no fill within "
          f"{FILL_WINDOW_S}s {no_fill} (fill rate "
          f"{len(d) / max(len(d) + no_fill, 1):.0%})")
    for sport, g in d.groupby("sport"):
        u_ent = np.where(g.won == 1, (1 - g.entry) / g.entry, -1.0)
        u_tape = np.where(g.won == 1, (1 - g.cost) / g.cost, -1.0)
        pm = pd.DataFrame({"m": g.market.values, "u": u_tape}).groupby("m").u.sum()
        t_m = pm.mean() / (pm.std() / np.sqrt(len(pm))) if len(pm) > 3 else float("nan")
        slip = (g.cost - g.entry).mean()
        print(f"  {sport}: n={len(g)} markets={g.market.nunique()}  "
              f"claimed(entry) ROI={u_ent.mean():+.1%}  TAPE ROI={u_tape.mean():+.1%}  "
              f"avg slip={slip:+.3f}  clustered t={t_m:.2f}")
        gg = g.copy()
        gg["u"] = u_tape
        gg["week"] = pd.to_datetime(gg.ts, unit="s", utc=True).dt.strftime("%G-W%V")
        wk = gg.groupby("week").agg(n=("u", "size"), tape_roi=("u", "mean"))
        print(wk.round(3).to_string())


STAGES = dict(fetch=stage_fetch, score=stage_score)
if __name__ == "__main__":
    for s in (sys.argv[1:] or list(STAGES)):
        STAGES[s]()
