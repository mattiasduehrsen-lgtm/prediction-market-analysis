"""
For each zombie order (placed but not in CSV), query Polymarket CLOB to
determine actual fill state and the market's resolution outcome, then
compute realized PnL the user actually saw vs what the bot recorded ($0).
"""
from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from src.bot.clob_auth import get_client
import requests

OUT_5M_LIVE = ROOT / "output" / "5m_live"
BOT_LOG = ROOT / "bot.log"

# Extended ORDER pattern to also capture the slug if it appears nearby.
# Bot log structure: ORDER lines don't carry slug directly. We need to grab
# the NEW WINDOW line preceding the ORDER (same pos_id) via earlier context.
# Simpler: grab full order_id from ORDER line then ask CLOB.
ORDER_RE = re.compile(
    r"\[LIVE5M\] ORDER\s+(\w{8})\s*\|\s*(\w+)\s+(\w+)\s+limit\s+BUY\s+([\d.]+)\s+shares\s+@\s+([\d.]+)\s*\|\s*order_id=(0x[\da-f]+)\.\.\."
)


def find_full_order_id(client, prefix: str) -> str | None:
    """The bot logs only first 16 hex chars of order_id. Need full ID for queries."""
    # We can't search by prefix via the CLOB API. Instead look at recent
    # post_order log lines around the ORDER timestamp — but bot already prints
    # only the prefix. Try to find a full id by other means.
    # Workaround: many orders may have been cancelled-but-on-book; if so
    # get_open_orders() would have shown them. They aren't there now (we
    # confirmed). So orders are EITHER filled OR expired.
    # The CLOB API has get_order(order_id) but needs the full id.
    return None


def main():
    if not BOT_LOG.exists():
        print(f"No bot.log at {BOT_LOG}")
        return

    csv_pids = set()
    for csvf in OUT_5M_LIVE.glob("trades_*.csv"):
        with open(csvf, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pid = (row.get("position_id") or "").strip()
                if pid:
                    csv_pids.add(pid)

    # Capture ORDER + the slug from the preceding NEW WINDOW line for the same asset
    zombies = []
    print("Scanning bot.log for zombies + their slugs ...")
    last_window_for_asset = {}  # asset -> (slug, ts_seen)
    with BOT_LOG.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # Track most-recent NEW WINDOW per asset for context
            wm = re.search(r"\[NEW WINDOW\] (\w+-updown-15m-\d+) \|", line)
            if wm:
                slug = wm.group(1)
                asset = slug.split("-")[0].upper()
                last_window_for_asset[asset] = slug
                continue
            m = ORDER_RE.search(line)
            if not m:
                continue
            pid, asset, side, shares, price, oid_prefix = m.groups()
            if pid in csv_pids:
                continue
            zombies.append({
                "pos_id": pid, "asset": asset, "side": side,
                "shares": float(shares), "price": float(price),
                "order_id_prefix": oid_prefix,
                "slug_guess": last_window_for_asset.get(asset, ""),
            })

    if not zombies:
        print("No zombies — nothing to reconcile.")
        return

    print(f"\nReconciling {len(zombies)} zombies via Polymarket CLOB...\n")

    total_committed = 0.0
    total_realized = 0.0
    total_unresolved = 0

    sess = requests.Session()
    print(f"{'pos':>10} {'asset':>5} {'side':>5} {'shares':>7} {'price':>6} {'slug':>32} {'winner':>8} {'pnl':>10}")
    print("-" * 100)

    for z in zombies:
        slug = z["slug_guess"]
        # Look up the market from CLOB
        if not slug:
            print(f"{z['pos_id']:>10} {z['asset']:>5} {z['side']:>5} {z['shares']:>7.2f} {z['price']:>6.3f} {'NO SLUG':>32}")
            continue
        try:
            r = sess.get(f"https://clob.polymarket.com/markets/slug/{slug}", timeout=8)
            if r.status_code != 200:
                # Try the data-api alternative
                r = sess.get(f"https://gamma-api.polymarket.com/markets?slug={slug}", timeout=8)
            mkt = r.json() if r.status_code == 200 else None
            if isinstance(mkt, list) and mkt:
                mkt = mkt[0]
        except Exception as e:
            print(f"{z['pos_id']:>10} {z['asset']:>5} {z['side']:>5} {z['shares']:>7.2f} {z['price']:>6.3f} {slug:>32} fetch_err: {e}")
            continue

        if not mkt:
            print(f"{z['pos_id']:>10} {z['asset']:>5} {z['side']:>5} {z['shares']:>7.2f} {z['price']:>6.3f} {slug:>32} mkt_not_found")
            continue

        closed = mkt.get("closed", False)
        winning_outcome = None
        for t in mkt.get("tokens", []) or []:
            if t.get("winner"):
                winning_outcome = t.get("outcome")
                break
        # If gamma-api shape, the structure differs — try outcomes/outcomePrices
        if not winning_outcome and isinstance(mkt.get("outcomes"), list):
            try:
                op = mkt.get("outcomePrices")
                if isinstance(op, str):
                    import json as _j
                    op = _j.loads(op)
                if op and len(op) == len(mkt["outcomes"]):
                    for outcome, pricestr in zip(mkt["outcomes"], op):
                        if float(pricestr) > 0.5:
                            winning_outcome = outcome
                            break
            except Exception:
                pass

        cost = z["shares"] * z["price"]
        total_committed += cost
        if not closed or not winning_outcome:
            total_unresolved += 1
            print(f"{z['pos_id']:>10} {z['asset']:>5} {z['side']:>5} {z['shares']:>7.2f} {z['price']:>6.3f} {slug:>32} {'UNRESOLVED':>8}")
            continue

        # Did we win? Our side (UP or DOWN) matches winning_outcome
        won = (z["side"].upper() == str(winning_outcome).upper())
        # Assumes the order fully filled — best case. If it never filled, real PnL = 0.
        if won:
            pnl = z["shares"] * 1.0 - cost   # paid $cost, got $1 per winning share
        else:
            pnl = -cost
        total_realized += pnl
        marker = "+" if won else "-"
        print(f"{z['pos_id']:>10} {z['asset']:>5} {z['side']:>5} {z['shares']:>7.2f} {z['price']:>6.3f} {slug:>32} {winning_outcome:>8} {marker}${abs(pnl):>8.2f}")

        time.sleep(0.1)

    print()
    print(f"Total committed if all filled : ${total_committed:.2f}")
    print(f"Total realized PnL (if filled): ${total_realized:+.2f}")
    print(f"Unresolved markets             : {total_unresolved}")
    print()
    print("Note: 'realized PnL' assumes each zombie order FULLY filled at its")
    print("limit price. If a market never moved past the order price, it expired")
    print("with no fill and the real outcome was $0 (no win, no loss).")


if __name__ == "__main__":
    main()
