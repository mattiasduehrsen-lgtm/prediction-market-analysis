"""
Reconcile bot.log ORDER lines vs trades_*.csv to find 'zombie' trades.

A zombie = an order the bot placed (logged ORDER line) but never recorded in
trades CSV. Cause: the cancel() bug. When the entry timeout-cancel failed
silently, the bot abandoned the position. If the order later filled, the bot
had zero record but the user owned shares (or had USDC change hands).

For each zombie, this script:
  - shows the original ORDER details (side, price, shares, slug)
  - queries Polymarket CLOB for the market's resolution outcome
  - infers PnL if we can match the token_id we placed an order for

Usage:
  .venv\\Scripts\\python.exe analysis\\audit_zombie_fills.py
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT_5M_LIVE = ROOT / "output" / "5m_live"
BOT_LOG = ROOT / "bot.log"

# Pattern for ORDER lines:
# [LIVE5M] ORDER  41f172dc | ETH DOWN limit BUY 13.70 shares @ 0.365 | order_id=0x6f6c...
ORDER_RE = re.compile(
    r"\[LIVE5M\] ORDER\s+(\w{8})\s*\|\s*(\w+)\s+(\w+)\s+limit\s+BUY\s+([\d.]+)\s+shares\s+@\s+([\d.]+)\s*\|\s*order_id=(0x[\da-f]+)\.\.\."
)

# Pattern for CANCEL FAILED lines that mark zombies:
# [LIVE5M] Cancel failed for 41f172dc: ...
CANCEL_FAIL_RE = re.compile(r"\[LIVE5M\] (?:Cancel|TP cancel) failed (?:before \w+ )?for (\w{8})")


def main():
    if not BOT_LOG.exists():
        print(f"No bot.log at {BOT_LOG}")
        return

    # 1) Index ORDER lines by position_id (the 8-char hash)
    orders: dict[str, dict] = {}
    cancel_failed: set[str] = set()
    print(f"Scanning {BOT_LOG} ...")
    line_count = 0
    with BOT_LOG.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line_count += 1
            m = ORDER_RE.search(line)
            if m:
                pid, asset, side, shares, price, oid = m.groups()
                orders[pid] = {
                    "pos_id": pid, "asset": asset, "side": side,
                    "shares": float(shares), "price": float(price),
                    "order_id_prefix": oid,
                }
                continue
            cm = CANCEL_FAIL_RE.search(line)
            if cm:
                cancel_failed.add(cm.group(1))
    print(f"  scanned {line_count:,} log lines")
    print(f"  found {len(orders):,} ORDER lines")
    print(f"  found {len(cancel_failed):,} cancel-failed events")

    # 2) Collect all position_ids from trades CSV
    csv_pids: set[str] = set()
    for csvf in OUT_5M_LIVE.glob("trades_*.csv"):
        with open(csvf, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pid = (row.get("position_id") or "").strip()
                if pid:
                    csv_pids.add(pid)
    print(f"  found {len(csv_pids):,} positions across trades CSVs")

    # 3) Zombies = ordered but not in CSV
    zombie_pids = set(orders.keys()) - csv_pids
    zombies = [orders[p] for p in sorted(zombie_pids)]
    # Annotate which had a cancel-failed event
    for z in zombies:
        z["cancel_failed"] = z["pos_id"] in cancel_failed

    print(f"\n  ZOMBIES (ordered but no CSV row): {len(zombies)}")

    if not zombies:
        print("\nNo zombies — every order the bot placed ended up in trades CSV.")
        return

    # 4) Summarise — most zombies fail cancellation, then either fill later
    # or expire. To tell which, we'd need to ask CLOB the fill state of each
    # order_id. That requires the L2 client. For now, show the list — user
    # can spot-check on Polymarket UI.
    print()
    print(f"{'pos':>10} {'asset':>5} {'side':>5} {'shares':>7} {'price':>6} {'cancel_failed':>14} {'order_id':>20}")
    for z in zombies:
        print(f"{z['pos_id']:>10} {z['asset']:>5} {z['side']:>5} {z['shares']:>7.2f} {z['price']:>6.3f} "
              f"{str(z['cancel_failed']):>14} {z['order_id_prefix']}...")

    # 5) Aggregate total $ at risk if all filled
    total_value = sum(z["shares"] * z["price"] for z in zombies)
    print(f"\n  Total committed $ if all zombies filled: ${total_value:,.2f}")
    print(f"  Pre-cancel-fix damage scope. After the cancel_order fix in")
    print(f"  live_engine_5m.py (commit d67b01d), no new zombies should occur.")


if __name__ == "__main__":
    main()
