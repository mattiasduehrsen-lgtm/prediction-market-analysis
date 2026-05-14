"""
Compare our recorded LIVE trades to Polymarket CLOB's own trade history.

If CLOB has matched orders for our wallet that we DID NOT record in
trades_*.csv, those are missing trades — i.e. the bot placed and filled
orders but never wrote the closure row. This explains "missed losses".

Run on laptop:
  .venv\\Scripts\\python.exe reconcile_clob_history.py
"""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path

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
    print("=== CLOB trade history vs local CSV reconciliation ===\n")

    # 1. Collect all entry/exit order IDs we've recorded
    recorded_order_ids = set()
    trades_by_orderid = {}
    for asset in ("BTC", "ETH", "SOL"):
        for r in read_csv(OUT_LIVE / f"trades_{asset}-15m.csv"):
            for k in ("entry_order_id", "exit_order_id", "tp_order_id"):
                v = r.get(k, "").strip()
                if v:
                    recorded_order_ids.add(v)
                    trades_by_orderid[v] = (asset, r.get("position_id", "?")[:8], k)
    print(f"Recorded order IDs across all LIVE trade rows: {len(recorded_order_ids)}\n")

    # 2. Query CLOB for our trade history
    try:
        from src.bot.clob_auth import get_client
        client = get_client()
    except Exception as e:
        print(f"[abort] could not get CLOB client: {e}")
        return

    # Different SDKs expose different methods. Try a few.
    history = None
    for method_name in ("get_trades", "get_trade_history", "get_my_trades"):
        m = getattr(client, method_name, None)
        if m is not None:
            try:
                history = m()
                print(f"Used client.{method_name}() — got {len(history) if hasattr(history,'__len__') else '?'} entries")
                break
            except Exception as e:
                print(f"client.{method_name}() raised: {e}")
    if history is None:
        # Try a low-level fetch via REST
        try:
            from py_clob_client_v2.constants import AMOY, POLYGON
            base = "https://clob.polymarket.com"
            # Trades endpoint — paginated
            api_creds = client.creds if hasattr(client, "creds") else None
            # Build the auth headers ourselves
            import requests
            from py_clob_client_v2.signing.eip712 import sign_clob_auth_message
            address = client.get_address()
            print(f"Wallet address: {address}")
            # Use Polymarket's data-api for activity instead
            url = f"https://data-api.polymarket.com/trades?user={address}&limit=100"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                history = r.json()
                print(f"Fetched {len(history)} trades from data-api")
            else:
                print(f"data-api returned {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"low-level fetch failed: {type(e).__name__}: {e}")

    if not history:
        print("[abort] no trade history available from any endpoint")
        return

    # 3. Compare
    print(f"\nFirst CLOB trade (sample):\n  {history[0] if history else '(none)'}")

    clob_orderids = set()
    clob_recent = []
    for t in history[:100]:
        oid = (t.get("id") or t.get("order_id") or t.get("orderID") or t.get("orderHash") or "").strip()
        if oid:
            clob_orderids.add(oid)
        clob_recent.append({
            "id": oid[:18] + "..." if len(oid) > 18 else oid,
            "timestamp": t.get("timestamp") or t.get("matched_at") or t.get("created_at"),
            "side": t.get("side"),
            "size": t.get("size") or t.get("size_matched"),
            "price": t.get("price") or t.get("match_price"),
            "in_records": oid in recorded_order_ids,
        })

    print(f"\nCLOB orders: {len(clob_orderids)}")
    print(f"Recorded order IDs:  {len(recorded_order_ids)}")
    common = clob_orderids & recorded_order_ids
    only_clob = clob_orderids - recorded_order_ids
    only_recorded = recorded_order_ids - clob_orderids
    print(f"In both:             {len(common)}")
    print(f"Only in CLOB:        {len(only_clob)}  <-- potential MISSING from local CSV")
    print(f"Only in local CSV:   {len(only_recorded)}  (likely just naming differences)")

    if only_clob:
        print("\nMOST RECENT CLOB-only orders (potential missed records):")
        for t in clob_recent:
            if not t["in_records"] and t["id"]:
                print(f"  {t}")


if __name__ == "__main__":
    main()
