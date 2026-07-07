"""R1 paper-validation status — the monitoring view for the pre-registered
triggers (COWORK_GRID_REFIT_RESULTS_2026-07-05.md §6; deployed v1.59).

Prints accrual pace, resolved W-L / ROI at the captured ask, distance to the
KILL (n>=60 & ROI<-10%) and GO-LIVE (n>=150 & ROI>+10% & excess) triggers, and
the r1_* event funnel. Reading this is NOT peeking: the KILL trigger is defined
on running ROI, so running ROI must be watched. The in-play test is different —
its pre-registration says no interim significance reads; this script therefore
only counts its sample size, never its win rate.

Run (laptop): .venv\\Scripts\\python.exe -u analysis\\r1_status.py
"""
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "esports_fade"


def main():
    csv = OUT / "r1_paper_trades.csv"
    if not csv.exists():
        print("R1: no gated paper bets logged yet (r1_paper_trades.csv absent)")
    else:
        df = pd.read_csv(csv)
        res = pd.read_parquet(ROOT / "cowork_snapshot" / "esports" / "resolutions.parquet")
        res = res[res.winning_outcome.notna()][["slug", "winning_outcome"]].drop_duplicates("slug")
        win = dict(zip(res.slug, res.winning_outcome))
        df["w"] = df.slug.map(win)
        df["won"] = [int(str(a).strip().lower() == str(b).strip().lower())
                     if isinstance(b, str) else np.nan
                     for a, b in zip(df.our_outcome, df.w)]
        r = df[df.w.notna()].copy()
        t0 = pd.to_datetime(df.ts.min(), unit="s", utc=True)
        days = max((pd.Timestamp.utcnow() - t0).total_seconds() / 86400, 1e-9)
        print(f"R1 gated paper bets: {len(df)} over {days:.1f} days "
              f"({len(df) / days:.1f}/day; spec estimated ~4.7/day)")
        if len(r):
            pnl = np.where(r.won == 1, (1 - r.best_ask) / r.best_ask, -1.0)
            print(f"  resolved: {len(r)}   W-L: {int(r.won.sum())}-{int(len(r) - r.won.sum())}   "
                  f"ROI@ask: {pnl.mean():+.1%}   units: {pnl.sum():+.2f}")
            print(f"  triggers: KILL n>=60 & ROI<-10% ({60 - len(r)} resolved to first read) | "
                  f"GO-LIVE n>=150 & ROI>+10% & excess P(<=0)<0.05")
        else:
            print("  no bets resolved yet")
        cols = [c for c in ("date", "slug", "our_outcome", "best_ask", "p_r1",
                            "r1_edge", "w") if c in df.columns]
        print(df[cols].tail(8).to_string(index=False))

    ev = OUT / "fade_events.jsonl"
    if ev.exists():
        c, skips = Counter(), Counter()
        with ev.open(encoding="utf-8") as fh:
            for line in fh:
                if '"r1_' not in line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                t = str(e.get("type", ""))
                if t.startswith("r1_"):
                    c[t] += 1
                    if t == "r1_skip":
                        skips[e.get("reason", "?")] += 1
        print(f"\nR1 event funnel: {dict(c)}")
        if skips:
            print(f"  skip reasons: {dict(skips)}")

    # In-play sample-size ONLY (no win rates — pre-registration forbids peeking)
    ip = ROOT / "output" / "cs2_inplay" / "paper_results.csv"
    if ip.exists():
        try:
            d = pd.read_csv(ip)
            side_col = next((x for x in ("side", "bet_side", "kind") if x in d.columns), None)
            n_b = int((d[side_col] == "B").sum()) if side_col else -1
            print(f"\nIn-play paper stream: {len(d)} rows; contrarian n={n_b} "
                  f"(test re-runs at n>=100 — no interim significance reads)")
        except Exception as e:
            print(f"\nIn-play count failed: {e}")


if __name__ == "__main__":
    main()
