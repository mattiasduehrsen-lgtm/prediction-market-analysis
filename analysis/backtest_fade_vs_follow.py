"""
Compare FADE vs FOLLOW strategy performance — on both LIVE realized and
PAPER signal data.

LIVE: from live_results.csv (post-evaluator, includes manual sells from
      reconciler)
PAPER: from paper_results.csv (run evaluate_paper.py first if stale)

Outputs per-strategy: trades, win rate, total cost, total PnL, ROI.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_RESULTS  = ROOT / "output" / "esports_fade" / "live_results.csv"
PAPER_RESULTS = ROOT / "output" / "esports_fade" / "paper_results.csv"


def analyze(csv_path: Path, label: str):
    if not csv_path.exists():
        print(f"\n=== {label} ===\n  (no data: {csv_path} missing — run evaluate_*.py first)")
        return
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    rows = [{k: v for k, v in r.items() if k is not None} for r in rows]

    # Filter to RESOLVED only (WIN/LOSS/TP_SOLD/TP_LOSS). Skip CANCELLED/UNRESOLVED.
    resolved = [r for r in rows
                if r.get("status") in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS")]
    # Only BUYs for LIVE (skip SELL rows that the evaluator folds in)
    resolved = [r for r in resolved if str(r.get("side", "BUY")).upper() != "SELL"]

    print(f"\n{'='*60}\n{label}\n{'='*60}")
    print(f"  Total resolved trades: {len(resolved)}")

    if not resolved:
        return

    # Bucket by strategy ('fade' / 'follow'); old rows might have empty strategy → default 'fade'
    by_strat = defaultdict(list)
    for r in resolved:
        s = (r.get("strategy") or "fade").lower()
        if s not in ("fade", "follow"):
            s = "fade"
        by_strat[s].append(r)

    print(f"\n{'strategy':>10} {'trades':>8} {'wins':>6} {'losses':>8} {'WR%':>7} "
          f"{'cost':>10} {'PnL':>11} {'ROI%':>8} {'avg PnL':>9}")
    print(f"  {'-'*78}")

    totals = {}
    for strat, items in sorted(by_strat.items()):
        wins   = sum(1 for r in items if r.get("status") in ("WIN", "TP_SOLD"))
        losses = sum(1 for r in items if r.get("status") in ("LOSS", "TP_LOSS"))
        # Cost: try cost_usd first (live), then our_bet (paper)
        cost = sum(float(r.get("cost_usd") or r.get("our_bet") or 0) for r in items)
        pnl  = sum(float(r.get("realized_pnl") or 0) for r in items)
        n    = wins + losses
        wr   = wins/n*100 if n else 0
        roi  = pnl/cost*100 if cost > 0 else 0
        avg  = pnl/n if n else 0
        totals[strat] = dict(n=n, wins=wins, losses=losses, cost=cost, pnl=pnl, wr=wr, roi=roi, avg=avg)
        print(f"  {strat:>10} {n:>8} {wins:>6} {losses:>8} {wr:>6.1f}% "
              f"${cost:>8.2f} ${pnl:>+8.2f} {roi:>+7.2f}% ${avg:>+7.3f}")

    # Combined
    n   = sum(t["n"] for t in totals.values())
    cost = sum(t["cost"] for t in totals.values())
    pnl  = sum(t["pnl"] for t in totals.values())
    wins = sum(t["wins"] for t in totals.values())
    print(f"  {'COMBINED':>10} {n:>8} {wins:>6} {n-wins:>8} {wins/n*100 if n else 0:>6.1f}% "
          f"${cost:>8.2f} ${pnl:>+8.2f} {pnl/cost*100 if cost>0 else 0:>+7.2f}%")

    # Conclusion
    if "fade" in totals and "follow" in totals:
        f = totals["fade"]; w = totals["follow"]
        print()
        better = "FOLLOW" if w["roi"] > f["roi"] else "FADE"
        gap_roi = abs(w["roi"] - f["roi"])
        print(f"  >> {better} outperformed by {gap_roi:.1f} pp ROI")
        print(f"     fade   sample size: {f['n']}  (need ~100 for confidence)")
        print(f"     follow sample size: {w['n']}  (need ~100 for confidence)")


def main():
    analyze(LIVE_RESULTS, "LIVE (real-money realized PnL)")
    analyze(PAPER_RESULTS, "PAPER (all-time signal performance)")
    print()


if __name__ == "__main__":
    main()
