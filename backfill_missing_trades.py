"""
Backfill missing LIVE trades into trades_*.csv based on Polymarket data-api.

For each Polymarket buy-without-sell condition_id that has no local trade row,
append a synthetic closure with:
  exit_reason = "BACKFILL_market_resolved"
  exit_price = 0.0  (since these positions resolved to zero)
  pnl_usd = net (sells_proceeds - buys_cost)

Run with --dry-run first to see what would be added.

  .venv\\Scripts\\python.exe backfill_missing_trades.py --dry-run
  .venv\\Scripts\\python.exe backfill_missing_trades.py
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import uuid
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


def fetch_all_trades(address):
    out = []
    offset = 0
    while True:
        r = requests.get(
            "https://data-api.polymarket.com/trades",
            params={"user": address, "limit": 500, "offset": offset},
            timeout=15,
        )
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        out.extend(page)
        if len(page) < 500:
            break
        offset += 500
    return out


def parse_asset_from_slug(slug):
    """btc-updown-15m-XXXX -> BTC, eth-updown-15m-XXXX -> ETH, etc."""
    s = slug.lower()
    if s.startswith("btc-"): return "BTC", "15m" if "-15m-" in s else "5m" if "-5m-" in s else "?"
    if s.startswith("eth-"): return "ETH", "15m" if "-15m-" in s else "5m" if "-5m-" in s else "?"
    if s.startswith("sol-"): return "SOL", "15m" if "-15m-" in s else "5m" if "-5m-" in s else "?"
    return None, None


def window_start_from_slug(slug):
    """Extract trailing epoch integer from e.g. 'eth-updown-15m-1778697000'."""
    try:
        return int(slug.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def read_csv(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Show what would be added without writing")
    args = ap.parse_args()

    address = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip()
    if not address:
        print("FAIL: POLYMARKET_PROXY_ADDRESS not in .env")
        return
    print(f"Wallet: {address}\n")

    print("Fetching trade history...")
    all_trades = fetch_all_trades(address)
    print(f"Got {len(all_trades)} trades")

    # Also fetch currently-redeemable positions — these are trades where the bot
    # bought, the market resolved, and the bot never called redeem(). They have
    # the same effect as "missed close": USDC was spent, tokens worthless or won
    # but no trade row in our CSV.
    print("Fetching current redeemable positions...")
    r = requests.get(
        "https://data-api.polymarket.com/positions",
        params={"user": address, "limit": 200},
        timeout=15,
    )
    open_positions = r.json() if r.status_code == 200 else []
    print(f"Got {len(open_positions)} positions ({sum(1 for p in open_positions if p.get('redeemable'))} redeemable)\n")

    # Group by condition
    by_cond = defaultdict(lambda: {"buys": [], "sells": [], "slug": ""})
    for t in all_trades:
        cond = t.get("conditionId") or t.get("condition_id") or ""
        if not cond: continue
        side = t.get("side", "").upper()
        by_cond[cond]["slug"] = t.get("slug", "") or by_cond[cond]["slug"]
        if side == "BUY":
            by_cond[cond]["buys"].append(t)
        elif side == "SELL":
            by_cond[cond]["sells"].append(t)

    # Local CSV conditions
    local_conds_by_asset = defaultdict(set)
    for asset in ("BTC", "ETH", "SOL"):
        for r in read_csv(OUT_LIVE / f"trades_{asset}-15m.csv"):
            cid = r.get("condition_id", "")
            if cid:
                local_conds_by_asset[asset].add(cid)

    # Add currently-redeemable positions to by_cond so they're treated as
    # missing trades (they have a buy but no sell on Polymarket's side).
    for p in open_positions:
        cond = p.get("conditionId") or ""
        if not cond:
            continue
        slug = p.get("slug", "") or by_cond[cond]["slug"]
        by_cond[cond]["slug"] = slug
        # If no buy recorded, synthesize one from the position's avgPrice and size.
        if not by_cond[cond]["buys"]:
            size = _f(p.get("size", 0))
            avg = _f(p.get("avgPrice", p.get("avg_price", 0)))
            if size > 0:
                by_cond[cond]["buys"].append({
                    "size": size, "price": avg,
                    "timestamp": int(p.get("entry_ts", 0)) or 0,
                })

    # Compute missing per asset
    to_backfill = defaultdict(list)
    for cond, info in by_cond.items():
        if not info["buys"]:
            continue
        slug = info["slug"]
        asset, window = parse_asset_from_slug(slug)
        if asset is None or window != "15m":
            continue  # only backfill 15m crypto trades; skip 5m/political markets
        if cond in local_conds_by_asset[asset]:
            continue  # already recorded
        # This is a missing trade
        cost     = sum(_f(b.get("size", 0)) * _f(b.get("price", 0)) for b in info["buys"])
        proceeds = sum(_f(s.get("size", 0)) * _f(s.get("price", 0)) for s in info["sells"])
        size_usd = round(cost, 2)
        shares   = sum(_f(b.get("size", 0)) for b in info["buys"])
        avg_entry = round(cost / shares, 4) if shares > 0 else 0.0
        # First buy is the entry timestamp; fall back to window-start epoch from slug
        # (used when the position came from /positions instead of /trades).
        first_buy_ts = min(int(b.get("timestamp", 0)) for b in info["buys"])
        if first_buy_ts == 0:
            first_buy_ts = window_start_from_slug(slug)
        # Sell timestamp (or market resolution time approximation)
        if info["sells"]:
            close_ts = max(int(s.get("timestamp", 0)) for s in info["sells"])
            exit_price = round(sum(_f(s.get("price", 0)) * _f(s.get("size", 0)) for s in info["sells"]) /
                               sum(_f(s.get("size", 0)) for s in info["sells"]), 4)
            exit_reason = "BACKFILL_partial_sell"
        else:
            # Approximate close time as 15min after first buy (window end)
            close_ts = first_buy_ts + 900
            exit_price = 0.0
            exit_reason = "BACKFILL_market_resolved"
        pnl = round(proceeds - cost, 4)
        # Side: prefer outcome from /positions or /trades response — the data-api
        # returns "Up" / "Down" alongside size/price. Falls back to "UP" if absent
        # (most of our bot's trades are UP; better than "?").
        side = "?"
        for src in (info["buys"] + open_positions if False else info["buys"]):
            o = (src.get("outcome") or "").upper()
            if o in ("UP", "DOWN"):
                side = o
                break
        if side == "?":
            # Try open_positions (where outcome is more reliably populated)
            for p in open_positions:
                if (p.get("conditionId") or p.get("condition_id")) == cond:
                    o = (p.get("outcome") or "").upper()
                    if o in ("UP", "DOWN"):
                        side = o
                        break
        if side == "?":
            side = "UP"   # conservative default — bot rarely buys DOWN on LIVE
        to_backfill[asset].append({
            "position_id":  f"bf_{uuid.uuid4().hex[:8]}",
            "condition_id": cond,
            "slug":         slug,
            "asset":        asset,
            "side":         side,
            "state":        "closed",
            "entry_price":  avg_entry,
            "take_profit":  0.6,
            "size_usd":     size_usd,
            "shares":       round(shares, 4),
            "entry_fee_usd": 0.0,
            "window_end_ts": close_ts,
            "opened_at":    float(first_buy_ts),
            "entry_order_id": "BACKFILL",
            "exit_order_id":  "BACKFILL",
            "token_id":     "",
            "exit_placed_at": 0.0,
            "exit_reason":  exit_reason,
            "tp_order_id":  "",
            "btc_price_at_window_start": 0,
            "btc_price_at_entry":       0,
            "btc_pct_change_at_entry":  0,
            "up_price_at_window_start": 0,
            "secs_remaining_at_entry":  0,
            "liquidity":    0,
            "price_60s_before_entry": 0,
            "price_30s_before_entry": 0,
            "price_velocity": 0,
            "price_60s_after_entry": 0,
            "exit_price":   exit_price,
            "exit_fee_usd": 0.0,
            "closed_at":    float(close_ts),
            "hold_seconds": close_ts - first_buy_ts,
            "pnl_usd":      pnl,
            "return_pct":   round(pnl / size_usd * 100, 2) if size_usd > 0 else 0.0,
            "our_side_won": "False",
            "best_skipped_opportunity": False,
        })

    print(f"=== Backfill plan ===\n")
    grand_total = 0.0
    for asset in ("BTC", "ETH", "SOL"):
        rows = to_backfill[asset]
        if not rows:
            continue
        tot = sum(r["pnl_usd"] for r in rows)
        grand_total += tot
        print(f"  {asset}: {len(rows)} rows  total PnL ${tot:+.2f}")
        for r in rows:
            ts = datetime.fromtimestamp(r["opened_at"], tz=timezone.utc).isoformat()
            print(f"    {ts}  cond={r['condition_id'][:14]}...  shares={r['shares']:.2f}  "
                  f"cost=${r['size_usd']:.2f}  exit=${r['exit_price']:.3f}  pnl=${r['pnl_usd']:+.2f}  "
                  f"{r['exit_reason']}")
    print(f"\n  GRAND TOTAL adjustment: ${grand_total:+.2f}")
    print()

    if args.dry_run:
        print("(dry-run; no files modified)")
        return

    # Write the rows
    written = 0
    for asset, rows in to_backfill.items():
        if not rows: continue
        f = OUT_LIVE / f"trades_{asset}-15m.csv"
        existing = read_csv(f)
        if not existing:
            print(f"  {asset}: trades CSV missing or empty; skipping")
            continue
        # Use the existing CSV's columns so we maintain compat
        fieldnames = list(existing[0].keys()) if existing else []
        with f.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames)
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fieldnames})
                written += 1
        print(f"  {asset}: appended {len(rows)} backfill rows -> {f.name}")

    print(f"\nBackfilled {written} missing trades. Restart dashboard to refresh totals.")


if __name__ == "__main__":
    main()
