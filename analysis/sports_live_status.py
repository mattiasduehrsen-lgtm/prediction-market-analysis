"""WTA live monitor — the pre-registered trigger view (WTA_LIVE_PLAN_2026-07-09.md).

Went live 2026-07-09. Reads output/sports_fade/live_results.csv, filters to WTA
fills, and reports resolved n / ROI / W-L against the two pre-registered triggers:
  KILL (revert to paper): live ROI < -15% at n >= 50 resolved fills, OR two
    consecutive daily-loss-cap hits.
  SCALE ($5->$10):        n >= 100 resolved fills AND live ROI > +5%.
Also shows the live-vs-paper health gap (paper stream = control) over the same
window. Reading running ROI is intended — the KILL trigger is defined on it.

Run (laptop): .venv\\Scripts\\python.exe -u analysis\\sports_live_status.py
"""
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "sports_fade"
GO_LIVE_TS = 1783628760  # 2026-07-09 ~22:26 UTC (PolyBotSports restart with WTA armed)


def _resolved(path):
    if not Path(path).exists():
        return pd.DataFrame()
    d = pd.read_csv(path)
    d["ts"] = pd.to_numeric(d.get("timestamp"), errors="coerce")
    d = d[d.fade_slug.astype(str).str.startswith("wta-", na=False)]
    d = d[pd.to_numeric(d.get("realized_pnl"), errors="coerce").notna()].copy()
    d["pnl"] = pd.to_numeric(d.realized_pnl)
    d["cost"] = pd.to_numeric(d.get("cost_usd"), errors="coerce")
    return d


def main():
    live = _resolved(OUT / "live_results.csv")
    live = live[live.ts >= GO_LIVE_TS]
    n = len(live)
    print(f"WTA LIVE since 2026-07-09 22:26 UTC")
    if n == 0:
        print("  no resolved WTA live fills yet (first reads land as Wimbledon/WTA "
              "matches settle; ~22 fades/day expected)")
    else:
        roi = live.pnl.sum() / live.cost.sum()
        wins = int((live.pnl > 0).sum())
        print(f"  resolved fills: {n}   W-L: {wins}-{n - wins}   "
              f"ROI: {roi:+.1%}   net: ${live.pnl.sum():+.2f}")
        print(f"  KILL if ROI<-15% at n>=50  -> {'*** KILL ZONE ***' if (n >= 50 and roi < -0.15) else f'{max(0,50-n)} fills to first read, ROI {roi:+.1%}'}")
        print(f"  SCALE to $10 at n>=100 & ROI>+5% -> {'*** SCALE OK ***' if (n >= 100 and roi > 0.05) else f'{max(0,100-n)} fills to read'}")

    # daily-loss-cap hit history (2 consecutive = KILL)
    ev = OUT / "fade_events.jsonl"
    if ev.exists():
        import json
        caps = []
        with ev.open(encoding="utf-8") as fh:
            for line in fh:
                if "skip_daily_loss_cap" in line:
                    try:
                        e = json.loads(line)
                        if e.get("ts", 0) >= GO_LIVE_TS:
                            caps.append(pd.to_datetime(e["ts"], unit="s", utc=True).date())
                    except Exception:
                        pass
        days = sorted(set(caps))
        if days:
            print(f"  daily-loss-cap hit on: {days}  (2 consecutive days = KILL)")

    # health: live vs paper over the live window (paper = control)
    paper = _resolved(OUT / "paper_results.csv")
    paper = paper[paper.ts >= GO_LIVE_TS]
    if len(paper) and n:
        proi = paper.pnl.sum() / paper.cost.sum()
        gap = (live.pnl.sum() / live.cost.sum()) - proi
        print(f"  health: live ROI vs paper ROI ({proi:+.1%}) over same window: "
              f"gap {gap:+.1%}  {'(investigate: live lags paper >10pp)' if gap < -0.10 and n >= 50 else ''}")


if __name__ == "__main__":
    main()
