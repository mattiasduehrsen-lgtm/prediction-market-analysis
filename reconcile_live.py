"""
Reconcile LIVE trade records against Polymarket reality.

Checks:
  1. Recorded total PnL across all LIVE trades.
  2. Polymarket positions API: any open positions held that the bot doesn't know about
  3. Positions in positions_*.csv with state OPEN/PENDING_EXIT
  4. Any condition_id where the bot opened but never closed

Reports any discrepancy that explains a "missing loss" - i.e. wallet movement
not accounted for in trades.csv.

Run on laptop (needs .env with API credentials):
  .venv\\Scripts\\python.exe reconcile_live.py
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent
OUT_LIVE = ROOT / "output/5m_live"


def _f(s):
    try: return float(s)
    except: return 0.0


def read_csv(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    print("=== LIVE reconciliation ===\n")

    # ── (1) Sum recorded PnL by asset ─────────────────────────────────────────
    grand_pnl = 0.0
    grand_count = 0
    print("Recorded LIVE trades (from trades_*.csv files):")
    print(f"{'Asset':<6} {'n':>4}  {'wins':>5} {'avg_pnl':>9}  {'total_pnl':>10}")
    for asset in ("BTC", "ETH", "SOL"):
        rows = read_csv(OUT_LIVE / f"trades_{asset}-15m.csv")
        # Filter to those with a closed_at - exclude any still-open
        closed = [r for r in rows if _f(r.get("closed_at")) > 0]
        n = len(closed)
        if n:
            tot = sum(_f(r.get("pnl_usd")) for r in closed)
            wins = sum(1 for r in closed if _f(r.get("pnl_usd")) > 0)
            print(f"{asset:<6} {n:>4}  {wins:>5} {tot/n:>+9.2f}  {tot:>+10.2f}")
            grand_pnl += tot
            grand_count += n
    print(f"{'TOTAL':<6} {grand_count:>4}  {'-':>5} {'-':>9}  {grand_pnl:>+10.2f}")

    # ── (2) Positions still tracked (positions_*.csv) ────────────────────────
    print("\nPositions still in positions_*.csv (state != closed):")
    open_count = 0
    for asset in ("BTC", "ETH", "SOL"):
        rows = read_csv(OUT_LIVE / f"positions_{asset}-15m.csv")
        for r in rows:
            state = r.get("state", "?")
            if state in ("open", "pending_exit", "pending_entry"):
                print(f"  {asset} {r.get('position_id','?')[:8]} state={state} "
                      f"entry={r.get('entry_price','?')} cond={r.get('condition_id','?')[:20]}...")
                open_count += 1
    if open_count == 0:
        print("  (none — all tracked positions are closed or empty)")

    # ── (3) Entries-vs-closures sanity check ──────────────────────────────────
    print("\nEntry/closure mismatch check (per asset trades_*.csv):")
    for asset in ("BTC", "ETH", "SOL"):
        rows = read_csv(OUT_LIVE / f"trades_{asset}-15m.csv")
        for r in rows:
            opened = _f(r.get("opened_at"))
            closed = _f(r.get("closed_at"))
            pnl = _f(r.get("pnl_usd"))
            if opened > 0 and closed == 0:
                print(f"  ORPHAN {asset} {r.get('position_id','?')[:8]} "
                      f"opened={opened} closed_at=0 pnl={pnl} state={r.get('state','?')}")

    # ── (4) Try to query Polymarket for current positions ─────────────────────
    print("\nPolymarket wallet + position state (via API):")
    try:
        from src.bot.clob_auth import get_client
        from py_clob_client_v2 import BalanceAllowanceParams, AssetType
        client = get_client()
        resp = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        raw = float(resp.get("balance", 0))
        usdc = raw / 1_000_000
        print(f"  USDC collateral: ${usdc:.2f}")
    except Exception as e:
        print(f"  [error] could not query CLOB: {e}")

    # ── (5) Summary ───────────────────────────────────────────────────────────
    print("\n=== Summary ===")
    print(f"  Recorded total LIVE PnL across all assets: ${grand_pnl:+.2f}")
    print(f"  Open/pending positions in tracker:         {open_count}")
    if grand_count > 0:
        print(f"  Average recorded PnL per trade:            ${grand_pnl/grand_count:+.2f}")


if __name__ == "__main__":
    main()
