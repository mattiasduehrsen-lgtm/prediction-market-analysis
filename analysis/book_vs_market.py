"""Book-vs-market diagnostic — is GRID-era Polymarket just tracking the books?
(2026-07-12; runs on the laptop where odds_capture + price_capture live.)

Joins, per CS2 series match:
  - bookmaker close: last active odds_capture snapshot >=2min before start
    (vig-normalized implied prob from the coefficients — NOT aggrement_score),
  - Polymarket T-5 mark: bid/ask from price_capture in the [3,8]min pre-start
    window (mid for calibration, ask for the tradable readout),
  - result: resolutions.parquet.

Readouts:
  1. corr / MAE / signed bias between book close and Polymarket mid.
  2. Brier: book vs market vs 50/50 blend on the joined resolved set.
  3. THE ACTIONABLE ONE: on disagreements |p_book - p_mid| >= 0.05, buy the
     side the book rates HIGHER, at the captured T-5 ask. If the books lead
     Polymarket, this prints money; if Polymarket just tracks the books with
     noise, it round-trips the spread.

Run (laptop): .venv\\Scripts\\python.exe -u analysis\\book_vs_market.py
Re-run any time — it uses whatever odds/capture history has accrued.
"""
import glob, json, re, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
from tape_backfill import _norm                      # csgo-suffix-aware norm
from esports_fade_bot import is_single_map_market

ODDS = ROOT / "output" / "odds_capture"
CAP = ROOT / "output" / "price_capture"
RES = ROOT / "cowork_snapshot" / "esports" / "resolutions.parquet"


def load_book_closes():
    rows = []
    for fp in sorted(glob.glob(str(ODDS / "odds_*.jsonl"))):
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                if '"kind": "winner"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if not (e.get("active_1") and e.get("active_2")):
                    continue
                c1, c2 = e.get("coeff_1"), e.get("coeff_2")
                if not c1 or not c2 or c1 <= 1.001 or c2 <= 1.001:
                    continue
                rows.append(e)
    d = pd.DataFrame(rows)
    if d.empty:
        print("no odds rows yet"); sys.exit(0)
    d["start_ts"] = pd.to_datetime(d.start_date, utc=True, errors="coerce").astype("int64") / 1e9
    d = d[d.ts <= d.start_ts - 120]
    d = d.sort_values("ts").groupby("slug").last().reset_index()
    i1, i2 = 1 / d.coeff_1, 1 / d.coeff_2
    d["p1_book"] = i1 / (i1 + i2)
    d["overround"] = (i1 + i2) - 1
    d["k1"] = d.team_1.map(_norm)
    d["k2"] = d.team_2.map(_norm)
    return d


def load_market_marks():
    """T-5 bid/ask per CS2 series market from price_capture."""
    recs = []
    for fp in sorted(glob.glob(str(CAP / "prices_*.jsonl"))):
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                if '"slug": "cs2' not in line and '"slug": "csgo' not in line:
                    continue
                if '"prop": 1' in line:
                    continue
                try:
                    recs.append(json.loads(line))
                except Exception:
                    pass
    d = pd.DataFrame(recs)
    d = d[~d.slug.map(is_single_map_market)]
    d["gs_ts"] = pd.to_datetime(d.gs, utc=True, errors="coerce").astype("int64") / 1e9
    d["tmin"] = (d.gs_ts - d.ts) / 60.0
    w = d[(d.tmin >= 3) & (d.tmin <= 8) & d.bid.notna() & d.ask.notna()]
    w = w.sort_values("ts").groupby(["cid", "outcome"]).last().reset_index()
    w["key"] = w.slug.str.extract(r"^(.*?-\d{4}-\d{2}-\d{2})")[0]
    w["nout"] = w.outcome.map(_norm)
    return w


def main():
    book = load_book_closes()
    mkt = load_market_marks()
    res = pd.read_parquet(RES)
    res = res[res.winning_outcome.notna()][["slug", "winning_outcome"]].drop_duplicates("slug")
    win = dict(zip(res.slug, res.winning_outcome))
    print(f"book closes: {len(book)} matches | market T-5 marks: {len(mkt)} series tokens")

    # index market marks by (team-pair) + slug date
    idx = {}
    for r in mkt.itertuples(index=False):
        md = re.search(r"(\d{4}-\d{2}-\d{2})", r.slug or "")
        if md:
            idx.setdefault((r.nout, md.group(1)), []).append(r)

    rows = []
    for b in book.itertuples(index=False):
        d0 = pd.Timestamp(b.start_ts, unit="s", tz="UTC")
        hit = None
        for dd in (0, -1, 1):
            ds = (d0 + pd.Timedelta(days=dd)).strftime("%Y-%m-%d")
            for k, p in ((b.k1, b.p1_book), (b.k2, 1 - b.p1_book)):
                for cand in idx.get((k, ds), []):
                    hit = (cand, p); break
                if hit: break
            if hit: break
        if not hit:
            continue
        m, p_book = hit   # p_book = book prob of the CAPTURED token's team
        mid = (m.bid + m.ask) / 2
        wn = win.get(m.slug)
        rows.append(dict(slug=m.slug, team=m.outcome, p_book=p_book, mid=mid,
                         ask=m.ask, bid=m.bid, ask_depth=m.ask_depth,
                         overround=b.overround,
                         won=(int(_norm(wn) == m.nout) if isinstance(wn, str) else np.nan)))
    d = pd.DataFrame(rows).drop_duplicates("slug")
    print(f"joined: {len(d)} matches ({int(d.won.notna().sum())} resolved) | "
          f"median overround {d.overround.median():+.3f}")
    if len(d) < 10:
        print("too few joins yet — re-run in a few days"); return

    print(f"\n1. tracking: corr={d.p_book.corr(d.mid):.3f}  "
          f"MAE={np.mean(np.abs(d.p_book - d.mid)):.3f}  "
          f"bias(book-mid)={np.mean(d.p_book - d.mid):+.3f}")
    r = d[d.won.notna()].copy()
    if len(r) >= 10:
        r["won"] = r.won.astype(int)
        def brier(p): return float(np.mean((np.clip(p, .02, .98) - r.won) ** 2))
        print(f"2. Brier (n={len(r)}): book={brier(r.p_book):.4f}  "
              f"market_mid={brier(r.mid):.4f}  blend={brier((r.p_book + r.mid) / 2):.4f}")
    dis = r[np.abs(r.p_book - r.mid) >= 0.05] if len(r) else pd.DataFrame()
    if len(dis):
        # buy the side the book rates higher, at the captured ask
        buy_this = dis[dis.p_book > dis.mid]      # book likes captured team
        buy_other = dis[dis.p_book < dis.mid]     # book likes the other side
        costs = pd.concat([buy_this.ask + 0.0, (1 - buy_other.bid)])
        wins = pd.concat([buy_this.won, 1 - buy_other.won])
        pnl = np.where(wins == 1, (1 - costs) / costs, -1.0)
        print(f"3. disagreements >=5c (n={len(dis)}): follow-the-book at executable "
              f"quotes -> ROI={pnl.mean():+.1%}  (W-L {int(wins.sum())}-{int((1-wins).sum())})")
        print(dis[["slug", "team", "p_book", "mid", "won"]].round(3).head(8).to_string(index=False))
    else:
        print("3. no >=5c disagreements among resolved joins yet")


if __name__ == "__main__":
    main()
