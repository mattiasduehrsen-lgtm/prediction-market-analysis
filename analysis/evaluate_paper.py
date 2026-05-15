"""
Evaluate realized PnL on logged paper trades.

For each row in output/esports_fade/paper_trades.csv:
  1. Fetch market state from CLOB (winner per token).
  2. If resolved: PnL = (shares - bet) if our_outcome won else -bet
  3. Else: mark UNRESOLVED.

Aggregates: total signals, resolved, win-rate, total PnL, ROI vs total bet.

Usage:
  .venv\\Scripts\\python.exe analysis\\evaluate_paper.py
"""
from __future__ import annotations

import csv
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "esports_fade"
CSV_PATH = OUT / "paper_trades.csv"
RESULTS_PATH = OUT / "paper_results.csv"

CACHE: dict[str, dict] = {}
SESSION = requests.Session()


def fetch_market(cid: str) -> dict | None:
    if cid in CACHE:
        return CACHE[cid]
    try:
        r = SESSION.get(f"https://clob.polymarket.com/markets/{cid}", timeout=8)
        if r.status_code != 200:
            return None
        j = r.json()
        CACHE[cid] = j
        return j
    except Exception:
        return None


def winning_outcome(mkt: dict) -> str | None:
    """Return the outcome string that won, or None if not yet resolved."""
    if not mkt:
        return None
    if not mkt.get("closed"):
        return None
    for t in mkt.get("tokens", []) or []:
        if t.get("winner"):
            return t.get("outcome")
    return None


def main():
    if not CSV_PATH.exists():
        print(f"No paper trades found at {CSV_PATH}")
        return
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    # Strip None keys (rows from older schema with fewer cols than current header)
    rows = [{k: v for k, v in r.items() if k is not None} for r in rows]
    print(f"Loaded {len(rows):,} paper signals")

    total_bet = 0.0
    total_pnl = 0.0
    n_resolved = 0
    n_wins = 0
    n_unresolved = 0
    n_skipped = 0

    out_rows = []
    unique_cids = list(set(r["fade_condition"] for r in rows if r.get("fade_condition")))
    print(f"Unique markets to resolve: {len(unique_cids)}")
    print("Fetching market states from CLOB...")
    for i, cid in enumerate(unique_cids):
        fetch_market(cid)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(unique_cids)}")
        time.sleep(0.05)

    print("Computing realized PnL...")
    for r in rows:
        cid = r["fade_condition"]
        our_outcome = r["our_outcome"]
        try:
            our_entry = float(r["our_entry"])
            bet = float(r["our_bet"])
            shares = float(r["our_shares_est"])
        except ValueError:
            n_skipped += 1
            continue

        mkt = CACHE.get(cid)
        winner = winning_outcome(mkt) if mkt else None
        if winner is None:
            n_unresolved += 1
            out_rows.append({**r, "status": "UNRESOLVED", "realized_pnl": ""})
            continue

        n_resolved += 1
        total_bet += bet
        if winner == our_outcome:
            pnl = shares - bet
            n_wins += 1
        else:
            pnl = -bet
        total_pnl += pnl
        out_rows.append({**r, "status": "WIN" if pnl > 0 else "LOSS",
                         "realized_pnl": round(pnl, 4)})

    # Write per-row results
    if out_rows:
        cols = list(out_rows[0].keys())
        with RESULTS_PATH.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for x in out_rows:
                w.writerow(x)
        print(f"\nWrote per-row results: {RESULTS_PATH}")

    # Summary
    print("\n" + "=" * 60)
    print("REALIZED PNL SUMMARY")
    print("=" * 60)
    print(f"  Total signals       : {len(rows):,}")
    print(f"  Resolved            : {n_resolved:,}")
    print(f"  Unresolved (open)   : {n_unresolved:,}")
    print(f"  Skipped (bad row)   : {n_skipped:,}")
    if n_resolved:
        wr = n_wins / n_resolved * 100
        roi = total_pnl / total_bet * 100 if total_bet else 0.0
        print(f"  Wins                : {n_wins:,}  ({wr:.1f}%)")
        print(f"  Total bet           : ${total_bet:,.2f}")
        print(f"  Total PnL           : ${total_pnl:+,.2f}")
        print(f"  ROI                 : {roi:+.2f}%")
        print(f"  Avg PnL per bet     : ${total_pnl/n_resolved:+.3f}")
    print()


if __name__ == "__main__":
    main()
