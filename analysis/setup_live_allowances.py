"""
One-time on-chain allowance setup for the esports fade bot.

Polymarket has separate allowances per exchange:
  - CTF Exchange (standard markets, used by CS2/LoL esports)
  - NEG_RISK Exchange (negative-risk markets, used by the 15m crypto bot)

The 15m bot already has NEG_RISK allowances set. This script sets the
STANDARD CTF allowance so the esports bot can BUY tokens.

Costs a tiny amount of MATIC for gas (typically <$0.05).

Usage:
  .venv\\Scripts\\python.exe analysis\\setup_live_allowances.py            # dry-run (shows what would be set)
  .venv\\Scripts\\python.exe analysis\\setup_live_allowances.py --confirm  # actually send the tx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.bot.clob_auth import get_client
from py_clob_client_v2 import BalanceAllowanceParams, AssetType


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="Actually send the approval transaction. Without this flag, dry-run only.")
    args = ap.parse_args()

    client = get_client()
    print("Checking current STANDARD CTF Exchange allowances...\n")

    try:
        b = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        bal_usd   = int(b.get("balance", 0)) / 1_000_000
        allow_usd = int(b.get("allowance", 0)) / 1_000_000
        print(f"  USDC balance   : ${bal_usd:.4f}")
        print(f"  USDC allowance : ${allow_usd:.4f}")
    except Exception as e:
        print(f"  ERROR reading allowance: {e}")
        sys.exit(1)

    if allow_usd >= 1000:
        print("\nAllowance already set (>= $1000). Nothing to do.")
        sys.exit(0)

    if not args.confirm:
        print("\nDRY RUN. To actually approve the CTF Exchange for USDC,")
        print("re-run with --confirm. This will send one on-chain tx (~$0.05 MATIC gas).")
        sys.exit(0)

    print("\nSending approval transaction...")
    try:
        # update_balance_allowance approves the exchange contract to pull
        # COLLATERAL (USDC) from the funder wallet.
        client.update_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        print("  approval sent. Waiting for confirmation...\n")
        # Re-check
        import time
        time.sleep(5)
        b = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        new_allow = int(b.get("allowance", 0)) / 1_000_000
        print(f"  USDC allowance now: ${new_allow:.4f}")
        if new_allow >= 1000:
            print("\nDONE. Esports bot can now place LIVE orders on standard markets.")
        else:
            print("\nApproval may still be confirming on-chain. Re-run this script in 30s to verify.")
    except Exception as e:
        print(f"  approval FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
