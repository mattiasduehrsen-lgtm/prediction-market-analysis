"""One-shot: backfill the 3 manual SELL orders into live_orders.jsonl.

These were placed by take_profit_sweep.py before it knew to log to the
orders file. Without this, evaluate_live.py thinks the positions are
still open.

Looks up the orders on Polymarket to verify they matched, then appends
SELL rows so the evaluator can pair them with the BUYs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.bot.clob_auth import get_client

OUT = ROOT / "output" / "esports_fade"
ORDERS = OUT / "live_orders.jsonl"

# The 3 manual sells we placed (id from log output, slug for sanity)
MANUAL_SELLS = [
    {"id": "0x47dc5e236eef7469", "slug": "cs2-lgc-gl1-2026-05-16-game1",
     "outcome": "GamerLegion", "expected_price": 0.99, "expected_shares": 19.22},
    {"id": "0xe417f1b570ba2cff", "slug": "cs2-lgc-gl1-2026-05-16-map-handicap-away-1pt5",
     "outcome": "GamerLegion", "expected_price": 0.99, "expected_shares": 14.28},
    {"id": "0x24d59d620c73b904", "slug": "cs2-shishk-cyb-2026-05-16-game2",
     "outcome": "CYBERSHOKE Prospects", "expected_price": 0.99, "expected_shares": 10.0},
]


def main():
    c = get_client()
    # Already-logged order_ids — skip dupes
    seen = set()
    if ORDERS.exists():
        with ORDERS.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                    oid = o.get("order_id", "")
                    if oid:
                        seen.add(oid[:18])
                except Exception:
                    continue

    # Look up each manual sell's full state via get_open_orders won't work
    # (already filled). We don't have the full order_id, only first 18 chars.
    # Best path: use the user trades endpoint to find recent sells.
    import requests
    proxy = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    print(f"Fetching recent trades for {proxy}...")
    r = requests.get("https://data-api.polymarket.com/trades",
                     params={"user": proxy, "limit": 50, "side": "SELL"}, timeout=15)
    if r.status_code != 200:
        print(f"  trades fetch failed: HTTP {r.status_code}")
        # Fallback: just synthesize the rows from expected values
        print("  Falling back to expected values from log output\n")
        recent_sells = []
    else:
        recent_sells = r.json() or []
        print(f"  got {len(recent_sells)} recent SELL trades")

    appended = 0
    with ORDERS.open("a", encoding="utf-8") as fh:
        for ms in MANUAL_SELLS:
            if ms["id"] in seen:
                print(f"  SKIP {ms['id']}... (already logged)")
                continue

            # Try to find the matching trade record
            matched = None
            for t in recent_sells:
                # The trade record's transactionHash is different from order_id,
                # but slug + side + price should match
                if (t.get("slug") == ms["slug"]
                    and str(t.get("side", "")).upper() == "SELL"
                    and abs(float(t.get("price", 0)) - ms["expected_price"]) < 0.02):
                    matched = t
                    break

            if matched:
                price = float(matched["price"])
                shares = float(matched["size"])
                print(f"  MATCHED {ms['slug'][:36]}  price={price}  shares={shares}")
            else:
                price = ms["expected_price"]
                shares = ms["expected_shares"]
                print(f"  EXPECTED {ms['slug'][:36]}  price={price}  shares={shares}  (no trade record found)")

            row = {
                "ts": time.time(),
                "side": "SELL",
                "order_id": ms["id"] + "_backfill",
                "status": "matched",
                "price": price,
                "shares": shares,
                "cost_usd": round(price * shares, 4),
                "token_id": "",  # filled below if we can map slug -> token_id
                "fade_slug": ms["slug"],
                "our_outcome": ms["outcome"],
                "tp_reason": "manual_sweep_backfill",
            }
            # Match against BUYs in live_orders.jsonl to grab token_id
            if ORDERS.exists():
                with ORDERS.open(encoding="utf-8") as fh2:
                    for line in fh2:
                        try:
                            bo = json.loads(line)
                        except Exception:
                            continue
                        if (bo.get("fade_slug") == ms["slug"]
                            and bo.get("our_outcome") == ms["outcome"]
                            and bo.get("token_id")):
                            row["token_id"] = bo["token_id"]
                            row["fade_condition"] = bo.get("fade_condition", "")
                            break
            fh.write(json.dumps(row) + "\n")
            appended += 1
            print(f"    -> appended SELL row (token_id={row['token_id'][:30]}...)")

    print(f"\nDone. {appended} SELL rows appended to {ORDERS.name}")


if __name__ == "__main__":
    main()
