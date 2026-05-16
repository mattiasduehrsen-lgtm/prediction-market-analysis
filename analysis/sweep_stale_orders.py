"""
One-time recovery sweep after the cancel() bug.

The bot was calling client.cancel() which raised AttributeError silently for
months. Result:
  - Cancelled-in-CSV orders may still be resting on the Polymarket book
  - Some of those orders later filled, leaving 'zombie' shares the bot has
    zero record of

This script:
  1. Lists every open order on the funder wallet
  2. Cancels them all via cancel_all() unless --dry-run
  3. Lists every CTF token balance (potential zombie shares from prior fills)
  4. Cross-references against trades_*.csv to identify which holdings the bot
     thinks are closed (those are the zombies)

Run BEFORE restarting PolyBot with the fix, so the bot starts from a clean slate.

Usage:
  .venv\\Scripts\\python.exe analysis\\sweep_stale_orders.py            # dry-run
  .venv\\Scripts\\python.exe analysis\\sweep_stale_orders.py --confirm  # actually cancel
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.bot.clob_auth import get_client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="Actually cancel orders. Default is dry-run.")
    args = ap.parse_args()

    client = get_client()

    # 1) Open orders
    print("=" * 60)
    print("OPEN ORDERS")
    print("=" * 60)
    try:
        orders = client.get_orders()
        if not orders:
            print("  (none — nothing resting on book)")
        else:
            for o in orders:
                side = o.get("side", "?")
                price = o.get("price", "?")
                size = o.get("size", "?")
                size_matched = o.get("size_matched", "?")
                asset = o.get("asset_id") or o.get("token_id", "?")
                oid = o.get("id") or o.get("orderID", "")
                print(f"  {oid[:18]}... {side:>4} {size} @ {price} (matched={size_matched}) token={str(asset)[:20]}...")
            print(f"\n  total: {len(orders)} open order(s)")
    except Exception as e:
        print(f"  ERROR fetching orders: {e}")
        orders = []

    # 2) Cancel sweep
    print()
    if orders and args.confirm:
        print("Cancelling all open orders via cancel_all()...")
        try:
            resp = client.cancel_all()
            print(f"  cancel_all() returned: {resp}")
        except Exception as e:
            print(f"  cancel_all() FAILED: {e}")
            print("  Falling back to per-order cancel_order()...")
            for o in orders:
                oid = o.get("id") or o.get("orderID", "")
                if not oid:
                    continue
                try:
                    client.cancel_order(oid)
                    print(f"    cancelled {oid[:18]}...")
                except Exception as ce:
                    print(f"    cancel_order {oid[:18]}... FAILED: {ce}")
    elif orders:
        print("DRY RUN — re-run with --confirm to actually cancel these orders.")

    # 3) Holdings audit — look up CTF balances for tokens the bot might own
    print()
    print("=" * 60)
    print("CTF TOKEN HOLDINGS (potential zombie shares)")
    print("=" * 60)
    # Collect every token_id the bot has ever traded
    tokens_seen: set[str] = set()
    out_5m_live = ROOT / "output" / "5m_live"
    for csvf in out_5m_live.glob("trades_*.csv"):
        with open(csvf, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                tid = (row.get("token_id") or "").strip()
                if tid and tid != "BACKFILL":
                    tokens_seen.add(tid)

    print(f"  tokens to check: {len(tokens_seen)} (from trades CSVs)")

    try:
        from py_clob_client_v2 import BalanceAllowanceParams, AssetType
    except Exception as e:
        print(f"  cannot import balance params: {e}")
        return

    zombies = []
    checked = 0
    for tid in sorted(tokens_seen):
        checked += 1
        try:
            b = client.get_balance_allowance(BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL, token_id=tid))
            bal_raw = b.get("balance", "0") or "0"
            bal = int(bal_raw)
            # CTF tokens are 6-decimal like USDC
            shares = bal / 1_000_000
            if shares > 0.01:
                zombies.append((tid, shares))
                print(f"  ZOMBIE: token={tid[:30]}... shares={shares:.4f}")
        except Exception as e:
            print(f"  balance check failed for {tid[:30]}...: {e}")
        if checked % 20 == 0:
            print(f"  ... checked {checked}/{len(tokens_seen)}")

    print()
    if not zombies:
        print("  No zombie shares found — all CSV-closed positions are truly closed on chain.")
    else:
        total_shares = sum(s for _, s in zombies)
        print(f"  Found {len(zombies)} positions with on-chain shares totaling {total_shares:.2f} shares.")
        print("  These are tokens the CSV says are 'closed' but you still own.")
        print("  They'll settle automatically when their markets resolve — no action required,")
        print("  but the recorded PnL in trades.csv is wrong for these.")


if __name__ == "__main__":
    main()
