"""Edge-window analysis: in-play ROI as a function of ENTRY DELAY after map-1
completion. Answers "at what latency does the edge die?" — the make-or-break,
since the paper bot has no live bo3_detect_lag_s data yet.

For each post-map-1 opportunity (from inplay_joined): model_live is fixed; we
sweep the delay D and price the bet at the market price prevailing at t1+D
(carry-forward from the trade stream). ROI per delay = the decay curve.
"""
from __future__ import annotations
import glob
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ES = ROOT / "cowork_snapshot" / "esports"
GD = ROOT / "cowork_snapshot" / "gamedata"
DELAYS = [0, 30, 60, 120, 300, 600, 900, 1800]   # seconds after map-1 completion
THR = 0.05
FRICTION = 0.02

def main():
    j = pd.read_parquet(GD / "inplay_joined.parquet")
    # need: cid, teamA, model_live, t1, A_won
    cids = set(j["cid"])
    tA = dict(zip(j["cid"], j["teamA"]))
    print(f"in-play opportunities: {len(j)}")

    # collect teamA price stream per cid in [t1-300, t1+2100]
    t1_by = dict(zip(j["cid"], j["t1"].astype("int64")))
    streams = {c: [] for c in cids}
    for sh in sorted(glob.glob(str(ES / "scrape" / "shards" / "*.parquet"))):
        try:
            d = pd.read_parquet(sh, columns=["conditionId", "outcome", "price", "timestamp"])
        except Exception:
            continue
        d = d[d["conditionId"].isin(cids)]
        if not len(d):
            continue
        d["timestamp"] = pd.to_numeric(d["timestamp"], errors="coerce")
        d["price"] = pd.to_numeric(d["price"], errors="coerce")
        for r in d.dropna(subset=["timestamp", "price"]).itertuples(index=False):
            if r.outcome != tA.get(r.conditionId):
                continue
            t1 = t1_by[r.conditionId]
            if t1 - 300 <= r.timestamp <= t1 + 2100:
                streams[r.conditionId].append((float(r.timestamp), float(r.price)))
    for c in streams:
        streams[c].sort()

    def price_at(cid, t):
        s = streams.get(cid) or []
        if not s:
            return None
        prev = None
        for ts, px in s:
            if ts <= t:
                prev = px
            else:
                break
        if prev is not None:
            return prev
        return s[0][1]  # no trade yet by t -> first available

    rows = list(j.itertuples(index=False))
    print(f"\n{'delay':>7}{'n':>6}{'WR':>6}{'ROI':>9}{'avg|mkt-model|':>16}")
    curve = []
    for D in DELAYS:
        bets = []; gaps = []
        for r in rows:
            t1 = int(r.t1)
            px = price_at(r.cid, t1 + D)
            if px is None or not (0.02 < px < 0.98):
                continue
            gaps.append(abs(r.model_live - px))
            edge = r.model_live - px
            if abs(edge) <= THR:
                continue
            if edge > 0:
                price = min(0.99, px + FRICTION); won = int(r.A_won)
            else:
                price = min(0.99, (1 - px) + FRICTION); won = 1 - int(r.A_won)
            bets.append((price, won))
        if not bets:
            print(f"{D:>7}{0:>6}"); continue
        cost = float(np.sum([b[0] for b in bets]))
        pnl = float(np.sum([(1 - b[0]) if b[1] else -b[0] for b in bets]))
        wr = float(np.mean([b[1] for b in bets])) * 100
        roi = pnl / cost * 100 if cost else 0
        agap = float(np.mean(gaps)) if gaps else float("nan")
        curve.append((D, len(bets), roi))
        print(f"{D:>7}{len(bets):>6}{wr:>5.0f}%{roi:>+8.1f}%{agap:>15.3f}")

    print("\nInterpretation:")
    print("  - ROI should DECAY with delay as the market reprices toward model_live.")
    print("  - The delay where ROI crosses ~0 = the max latency we can tolerate.")
    print("  - avg|mkt-model| shrinking with delay = market converging to our number.")

if __name__ == "__main__":
    main()
