"""
Reconcile manual sells done via the Polymarket UI.

The bot logs every SELL it places (via auto-TP or the take_profit_sweep
script) into live_orders.jsonl. But if the user clicks "Sell" on the
Polymarket UI directly, the bot has no record of it — which causes:

  - Bot's Open Positions panel keeps showing the position as open
  - evaluate_live.py assumes we still hold the shares at resolution time,
    miscounting realized PnL

This script periodically fetches the proxy wallet's recent SELL trades
from data-api.polymarket.com/trades, compares against what's in
live_orders.jsonl, and appends synthetic SELL rows for anything we
didn't already record. Tagged tp_reason='manual_sell_inferred' so it's
distinguishable from bot-placed sells.

Idempotent: re-running won't duplicate already-reconciled rows.

Usage:
  .venv\\Scripts\\python.exe analysis\\reconcile_polymarket_sells.py            # dry-run
  .venv\\Scripts\\python.exe analysis\\reconcile_polymarket_sells.py --confirm  # actually append
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

ORDERS_PATH = ROOT / "output" / "esports_fade" / "live_orders.jsonl"
PROXY       = os.environ.get("POLYMARKET_PROXY_ADDRESS", "").strip().lower()
TS_BUCKET   = 60     # group sells into 60-sec buckets for matching
SHARES_TOL  = 0.05   # consider matched if shares are within 0.05 of each other


def fetch_user_sells(limit: int = 200) -> list[dict]:
    """Return our proxy's recent SELL trades on Polymarket."""
    r = requests.get(
        "https://data-api.polymarket.com/trades",
        params={"user": PROXY, "limit": limit, "side": "SELL"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json() or []


def load_existing_sells() -> set[tuple[str, int]]:
    """Return {(token_id, ts_bucket)} for SELL rows already in live_orders.jsonl."""
    seen = set()
    if not ORDERS_PATH.exists():
        return seen
    with ORDERS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if str(o.get("side", "BUY")).upper() != "SELL":
                continue
            tid = str(o.get("token_id") or "")
            ts  = float(o.get("ts") or 0)
            if not tid or not ts:
                continue
            # Bucket the timestamp so wall-clock vs blockchain-recorded times
            # within ~60s of each other still match.
            seen.add((tid, int(ts // TS_BUCKET)))
    return seen


def load_existing_buys() -> dict[str, dict]:
    """Map token_id -> {fade_slug, our_outcome, fade_condition, strategy} from BUY rows.

    Used to enrich the synthetic SELL with context so the UI knows which match
    it belongs to.
    """
    by_tid = {}
    if not ORDERS_PATH.exists():
        return by_tid
    with ORDERS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if str(o.get("side", "BUY")).upper() != "BUY":
                continue
            tid = str(o.get("token_id") or "")
            if tid and tid not in by_tid:
                by_tid[tid] = {
                    "fade_slug":      o.get("fade_slug", ""),
                    "fade_condition": o.get("fade_condition", ""),
                    "our_outcome":    o.get("our_outcome", ""),
                    "strategy":       o.get("strategy", ""),
                }
    return by_tid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true",
                    help="Actually append synthetic SELL rows. Default is dry-run.")
    ap.add_argument("--limit", type=int, default=200,
                    help="Max Polymarket SELL records to fetch (default 200)")
    args = ap.parse_args()

    if not PROXY:
        print("ABORT: POLYMARKET_PROXY_ADDRESS missing from .env")
        sys.exit(1)

    print(f"Proxy:        {PROXY}")
    print(f"Mode:         {'EXECUTE' if args.confirm else 'DRY-RUN'}")
    print(f"orders file:  {ORDERS_PATH}\n")

    print("Fetching Polymarket SELL trades for our proxy...")
    try:
        sells = fetch_user_sells(args.limit)
    except Exception as e:
        print(f"ABORT: fetch failed: {e}")
        sys.exit(1)
    print(f"  got {len(sells)} SELL records\n")

    existing = load_existing_sells()
    buy_ctx  = load_existing_buys()
    print(f"Already-recorded SELL buckets in live_orders.jsonl: {len(existing)}")
    print(f"BUY context entries (token_id -> match meta): {len(buy_ctx)}\n")

    missing = []
    for t in sells:
        tid    = str(t.get("asset") or t.get("token_id") or "")
        ts     = float(t.get("timestamp") or 0)
        if not tid or not ts:
            continue
        bucket = int(ts // TS_BUCKET)

        # Already known? (within ±1 bucket for clock-skew safety)
        if any((tid, bucket + d) in existing for d in (-1, 0, 1)):
            continue

        # Is it ours to care about? Skip sells on tokens the bot never bought
        # (could be other manual user activity unrelated to the fade strategy).
        ctx = buy_ctx.get(tid)
        if not ctx:
            continue

        shares = float(t.get("size") or 0)
        price  = float(t.get("price") or 0)
        if shares < 0.01 or price <= 0:
            continue

        proceeds = round(shares * price, 4)
        outcome  = t.get("outcome") or ctx.get("our_outcome", "")

        missing.append({
            "ts":             ts,
            "side":           "SELL",
            "order_id":       (t.get("transactionHash") or "")[:42] + "_manual",
            "status":         "matched",
            "price":          price,
            "shares":         shares,
            "cost_usd":       proceeds,   # for SELL rows, this is PROCEEDS
            "token_id":       tid,
            "fade_condition": ctx.get("fade_condition", ""),
            "fade_slug":      ctx.get("fade_slug", ""),
            "our_outcome":    outcome,
            "strategy":       ctx.get("strategy", ""),
            "tp_reason":      "manual_sell_inferred",
            "tx_hash":        t.get("transactionHash", ""),
        })

    if not missing:
        print("No manual sells to reconcile. live_orders.jsonl is in sync.")
        return

    print(f"FOUND {len(missing)} manual SELL trade(s) not in live_orders.jsonl:\n")
    total_proceeds = 0.0
    for m in missing:
        slug    = (m.get("fade_slug") or "")[:36]
        outcome = (m.get("our_outcome") or "")[:14]
        ts_iso  = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(m["ts"]))
        print(f"  {ts_iso}  {slug:>36}  {outcome:>14}  {m['shares']:>6.2f}sh @ ${m['price']:.3f}  -> ${m['cost_usd']:.2f}")
        total_proceeds += m["cost_usd"]
    print(f"\n  total proceeds: ${total_proceeds:,.2f}")

    if not args.confirm:
        print("\nDRY RUN. Re-run with --confirm to append these synthetic SELL rows.")
        return

    with ORDERS_PATH.open("a", encoding="utf-8") as fh:
        for m in missing:
            fh.write(json.dumps(m) + "\n")
    print(f"\nAppended {len(missing)} SELL rows.")
    print("Re-run analysis/evaluate_live.py to refresh PnL (or wait for the next eval task fire).")


if __name__ == "__main__":
    main()
