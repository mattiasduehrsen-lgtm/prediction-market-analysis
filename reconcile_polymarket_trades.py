"""
Fetch our wallet's complete trade history from Polymarket's data-api,
then compare BUY/SELL pairs per condition_id. Any condition where we BOUGHT
but never SOLD = missing exit = a position that lost ($0 resolution) but
was never recorded in our local trades_*.csv.

Run on laptop:
  .venv\\Scripts\\python.exe reconcile_polymarket_trades.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parent
OUT_LIVE = ROOT / "output/5m_live"


def _f(s):
    try: return float(s)
    except: return 0.0


def get_wallet_address():
    """
    Get the Polymarket PROXY (Safe) address — that's where trades are recorded.
    client.get_address() returns the EOA signer which has NO trades.
    """
    import os
    proxy = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    if proxy:
        return proxy
    try:
        from src.bot.clob_auth import get_client
        return get_client().get_address()
    except Exception:
        return None


def fetch_trades(address, page_size=500, max_pages=20):
    """Fetch ALL trades from Polymarket data-api via pagination."""
    out = []
    offset = 0
    for _ in range(max_pages):
        url = "https://data-api.polymarket.com/trades"
        params = {"user": address, "limit": page_size, "offset": offset}
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        out.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return out


def main():
    address = get_wallet_address()
    print(f"Wallet address: {address}\n")

    print("Fetching trade history from Polymarket data-api...")
    trades = fetch_trades(address, limit=500)
    print(f"Got {len(trades)} trades total\n")

    # Group by conditionId
    by_cond = defaultdict(lambda: {"buys": [], "sells": [], "slug": ""})
    for t in trades:
        cond = t.get("conditionId") or t.get("condition_id") or ""
        side = t.get("side", "").upper()
        slug = t.get("slug", t.get("eventSlug", ""))
        if not cond:
            continue
        by_cond[cond]["slug"] = slug or by_cond[cond]["slug"]
        if side == "BUY":
            by_cond[cond]["buys"].append(t)
        elif side == "SELL":
            by_cond[cond]["sells"].append(t)

    print(f"Unique condition IDs traded: {len(by_cond)}\n")

    # Now compare to our local CSV: load all closed trades by condition_id
    local_conditions = set()
    for asset in ("BTC", "ETH", "SOL"):
        f = OUT_LIVE / f"trades_{asset}-15m.csv"
        if not f.exists(): continue
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                cond = r.get("condition_id", "")
                if cond:
                    local_conditions.add(cond)
    print(f"Local CSV has trade rows for {len(local_conditions)} unique condition_ids\n")

    # Find conditions where we BOUGHT on Polymarket but have NO local trade row
    missing = []
    for cond, info in by_cond.items():
        if not info["buys"]:
            continue   # no buy — not our entry
        if cond in local_conditions:
            continue   # we have a local record for this condition

        # This is a buy on Polymarket with no local CSV record!
        buys_cost = sum(_f(b.get("size", 0)) * _f(b.get("price", 0)) for b in info["buys"])
        sells_proceeds = sum(_f(s.get("size", 0)) * _f(s.get("price", 0)) for s in info["sells"])
        net = sells_proceeds - buys_cost
        slug = info["slug"]
        first_buy_ts = min((t.get("timestamp", 0) for t in info["buys"]), default=0)
        try:
            first_buy_dt = datetime.fromtimestamp(int(first_buy_ts), tz=timezone.utc).isoformat()
        except Exception:
            first_buy_dt = "?"
        missing.append({
            "condition_id": cond,
            "slug": slug,
            "first_buy_utc": first_buy_dt,
            "n_buys": len(info["buys"]),
            "n_sells": len(info["sells"]),
            "buys_cost":   round(buys_cost, 2),
            "sells_proceeds": round(sells_proceeds, 2),
            "net_pnl":     round(net, 2),
        })

    print(f"=== Positions bought on Polymarket but missing from local CSV: {len(missing)} ===\n")
    for m in sorted(missing, key=lambda x: x["first_buy_utc"]):
        print(f"  {m['first_buy_utc']}  slug={m['slug'][:40] if m['slug'] else '?'}")
        print(f"    cond={m['condition_id'][:20]}...  buys={m['n_buys']}  sells={m['n_sells']}  "
              f"cost=${m['buys_cost']}  proceeds=${m['sells_proceeds']}  net=${m['net_pnl']:+.2f}")
        print()

    total_missing_pnl = sum(m["net_pnl"] for m in missing)
    print(f"Total UNRECORDED net PnL: ${total_missing_pnl:+.2f}")


if __name__ == "__main__":
    main()
