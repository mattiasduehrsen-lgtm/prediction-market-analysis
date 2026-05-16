"""
One-shot take-profit sweep: SELL any open CTF positions where the current
market price is high enough to lock in profit instead of waiting for
resolution.

Why this exists:
  The esports bot's original design was "hold to resolution" — markets
  auto-credit winners. But when a market converges early (e.g., a team is
  winning Map 2 and the price gaps to $0.99), we're tying up capital and
  carrying the (tiny) tail risk that the market reverses. Selling at $0.97
  for sure beats waiting for $1.00 with even 0.5% reversal risk, and frees
  USDC for the next trade.

What it does:
  1. Fetch every open position from data-api /positions
  2. For each, query the CLOB best bid (what someone will pay us right now)
  3. If best_bid >= MIN_TP_PRICE, place a SELL GTC at best_bid

Usage:
  .venv\\Scripts\\python.exe analysis\\take_profit_sweep.py            # dry-run
  .venv\\Scripts\\python.exe analysis\\take_profit_sweep.py --confirm  # actually sell
  .venv\\Scripts\\python.exe analysis\\take_profit_sweep.py --confirm --min-price 0.90
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import requests
from src.bot.clob_auth import get_client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="Actually place SELL orders. Default is dry-run.")
    ap.add_argument("--min-price", type=float, default=0.95,
                    help="Minimum current best bid to trigger a sell (default 0.95)")
    ap.add_argument("--cap-cents", type=int, default=99,
                    help="Cap our sell price at this many cents (default 99 — don't ask for 100c)")
    args = ap.parse_args()

    proxy = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    if not proxy:
        print("ABORT: POLYMARKET_PROXY_ADDRESS missing")
        sys.exit(1)

    print(f"Funder wallet: {proxy}")
    print(f"Mode         : {'EXECUTE' if args.confirm else 'DRY-RUN'}")
    print(f"Min TP price : {args.min_price}")
    print(f"Sell price cap: {args.cap_cents}c\n")

    # 1. Fetch open positions
    try:
        r = requests.get("https://data-api.polymarket.com/positions",
                         params={"user": proxy, "limit": 200}, timeout=15)
        r.raise_for_status()
        positions = r.json()
    except Exception as e:
        print(f"ABORT: positions fetch failed: {e}")
        sys.exit(1)

    # Filter to open (size > 0, not redeemable)
    open_positions = [p for p in positions
                      if float(p.get("size") or 0) > 0.01 and not p.get("redeemable")]
    print(f"Open positions: {len(open_positions)}\n")

    if not open_positions:
        print("Nothing open. Exiting.")
        sys.exit(0)

    client = get_client()
    candidates = []
    for p in open_positions:
        slug   = p.get("slug", "?")[:40]
        size   = float(p.get("size") or 0)
        avg    = float(p.get("avgPrice") or p.get("avg_price") or 0)
        outcome = p.get("outcome", "?")
        token_id = p.get("asset") or p.get("token_id", "")
        if not token_id:
            continue

        # Best bid = HIGHEST price someone is offering to buy at. That's what
        # we'd receive selling now. The CLOB returns a dict with "bids" sorted
        # ascending — best bid is the LAST element.
        try:
            ob = client.get_order_book(str(token_id))
            bids = (ob or {}).get("bids") if isinstance(ob, dict) else []
            best_bid = 0.0
            if bids:
                last = bids[-1]
                if isinstance(last, dict):
                    best_bid = float(last.get("price") or 0)
                else:
                    best_bid = float(getattr(last, "price", 0))
        except Exception as e:
            print(f"  {slug:>40}  orderbook err: {e}")
            continue

        unrealized = (best_bid - avg) * size
        marker = "*** TP ***" if best_bid >= args.min_price else ""
        print(f"  {slug:>40}  {outcome:>10}  size={size:>6.2f}  avg={avg:.3f}  bid={best_bid:.3f}  unrealized=${unrealized:+.2f} {marker}")

        if best_bid >= args.min_price:
            candidates.append({
                "slug": slug, "outcome": outcome, "size": size, "avg": avg,
                "best_bid": best_bid, "token_id": str(token_id),
            })

    if not candidates:
        print("\nNo positions above min-price threshold. Nothing to sell.")
        sys.exit(0)

    print(f"\n{len(candidates)} position(s) eligible for TP sell:")
    total_proceeds = 0.0
    for c in candidates:
        sell_price = min(args.cap_cents / 100.0, c["best_bid"])
        proceeds = sell_price * c["size"]
        total_proceeds += proceeds
        c["sell_price"] = sell_price
        print(f"  -> SELL {c['size']:.2f} of {c['outcome'][:20]} @ {sell_price:.2f}  =  ${proceeds:.2f}")

    print(f"\nEstimated total proceeds: ${total_proceeds:,.2f}")

    if not args.confirm:
        print("\nDRY RUN. Re-run with --confirm to actually place sells.")
        sys.exit(0)

    # 2. Place sells
    print("\nPlacing SELL orders...")
    from py_clob_client_v2 import OrderArgs, OrderType
    from py_clob_client_v2.order_builder.constants import SELL
    import json as _json

    live_orders_path = ROOT / "output" / "esports_fade" / "live_orders.jsonl"

    sent = 0
    for c in candidates:
        sell_size  = round(c["size"], 2)
        sell_price = round(c["sell_price"], 2)
        try:
            args_o = OrderArgs(price=sell_price, size=sell_size, side=SELL, token_id=c["token_id"])
            signed = client.create_order(args_o)
            resp = client.post_order(signed, OrderType.GTC)
            oid = (resp or {}).get("orderID") or (resp or {}).get("orderId") or ""
            status = (resp or {}).get("status", "")
            print(f"  SELL {sell_size}@{sell_price} {c['outcome'][:20]:>20}  id={oid[:18]}... status={status}")
            sent += 1
            # Log to live_orders.jsonl so evaluator can compute realized PnL
            with live_orders_path.open("a", encoding="utf-8") as fh:
                fh.write(_json.dumps({
                    "ts":         time.time(),
                    "side":       "SELL",
                    "order_id":   oid,
                    "status":     status,
                    "price":      sell_price,
                    "shares":     sell_size,
                    "cost_usd":   round(sell_price * sell_size, 4),  # proceeds for SELL
                    "token_id":   c["token_id"],
                    "our_outcome": c.get("outcome", ""),
                    "tp_reason":  "manual_sweep",
                }) + "\n")
        except Exception as e:
            print(f"  SELL FAILED for {c['outcome']}: {e}")
        time.sleep(0.5)

    print(f"\nDone. {sent}/{len(candidates)} orders sent.")


if __name__ == "__main__":
    main()
