"""
Backtest: what would CANCELLED LIVE trades have made if they'd filled?

For each cancelled BUY in live_orders.jsonl (orders the bot placed at
our_entry + 1c slippage but didn't fill within the 12s timeout):

  1. Look up the market's actual resolution from CLOB
  2. Assume the order WOULD have filled at the requested limit price
  3. PnL = (shares × $1 if won, $0 if lost) - cost

This is an OPTIMISTIC estimate — in reality, the order didn't fill because
the orderbook moved away from our limit. To actually capture these trades
we'd have had to pay 1-3c more per share. So real PnL would be slightly
lower than what this script reports.

Usage:
  .venv\\Scripts\\python.exe analysis\\backtest_cancelled_trades.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from collections import defaultdict
import requests

ROOT = Path(__file__).resolve().parents[1]
ORDERS = ROOT / "output" / "esports_fade" / "live_orders.jsonl"

_market_cache: dict = {}
SESSION = requests.Session()


def fetch_winner(condition_id: str) -> str | None:
    """Return the winning outcome string, or None if unresolved."""
    if condition_id in _market_cache:
        return _market_cache[condition_id]
    try:
        r = SESSION.get(f"https://clob.polymarket.com/markets/{condition_id}", timeout=6)
        if r.status_code != 200:
            return None
        j = r.json()
        if not j.get("closed"):
            _market_cache[condition_id] = None
            return None
        for t in j.get("tokens", []) or []:
            if t.get("winner"):
                w = t.get("outcome")
                _market_cache[condition_id] = w
                return w
    except Exception:
        return None
    return None


def main():
    if not ORDERS.exists():
        print("No live_orders.jsonl"); sys.exit(1)
    rows = [json.loads(l) for l in ORDERS.open(encoding="utf-8") if l.strip()]

    cancelled = [
        r for r in rows
        if str(r.get("side", "BUY")).upper() == "BUY"
        and str(r.get("status", "")).lower() in ("cancelled", "canceled")
    ]
    print(f"Cancelled BUY rows found: {len(cancelled)}\n")
    if not cancelled:
        return

    # Unique markets among cancelled trades
    cids = sorted({r.get("fade_condition") for r in cancelled if r.get("fade_condition")})
    print(f"Fetching resolution status for {len(cids)} unique markets...")
    for i, cid in enumerate(cids):
        fetch_winner(cid)
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(cids)}")
        time.sleep(0.05)

    # Backtest each cancelled trade
    results = []
    n_unresolved = 0
    n_wins = 0
    n_losses = 0
    total_pnl = 0.0
    total_cost = 0.0

    for r in cancelled:
        cid    = r.get("fade_condition", "")
        out    = r.get("our_outcome", "")
        slug   = r.get("fade_slug", "")
        strat  = r.get("strategy", "fade")
        req_p  = float(r.get("requested_price") or r.get("price") or 0)
        req_sh = float(r.get("requested_shares") or r.get("shares") or 0)
        cost   = req_p * req_sh

        if not cid or req_p <= 0 or req_sh <= 0:
            continue

        winner = _market_cache.get(cid)
        if not winner:
            n_unresolved += 1
            results.append({"slug": slug, "outcome": out, "strat": strat,
                            "price": req_p, "shares": req_sh, "cost": cost,
                            "winner": "(unresolved)", "pnl": None})
            continue

        if winner == out:
            pnl = req_sh * 1.0 - cost
            n_wins += 1
        else:
            pnl = -cost
            n_losses += 1
        total_pnl  += pnl
        total_cost += cost
        results.append({"slug": slug, "outcome": out, "strat": strat,
                        "price": req_p, "shares": req_sh, "cost": cost,
                        "winner": winner, "pnl": pnl})

    # Per-trade breakdown (top 20 + bottom)
    print()
    print("=" * 100)
    print("PER-CANCELLED-TRADE HYPOTHETICAL PNL")
    print("=" * 100)
    print(f"{'slug':>40}  {'strat':>6}  {'side bought':>16}  {'price':>6} {'sh':>6}  {'cost':>6}  {'winner':>16}  {'PnL':>8}")
    for r in sorted(results, key=lambda x: x["pnl"] if x["pnl"] is not None else -999):
        pnl_str = f"${r['pnl']:+.2f}" if r["pnl"] is not None else " open  "
        print(f"  {r['slug'][:38]:>38}  {r['strat']:>6}  {r['outcome'][:16]:>16}  {r['price']:>6.3f} {r['shares']:>6.2f}  ${r['cost']:>5.2f}  {r['winner'][:16]:>16}  {pnl_str:>8}")

    n_resolved = n_wins + n_losses
    print()
    print("=" * 60)
    print("HYPOTHETICAL BACKTEST SUMMARY")
    print("=" * 60)
    print(f"  cancelled trades       : {len(cancelled)}")
    print(f"  resolved markets       : {n_resolved} ({n_wins} wins / {n_losses} losses)")
    print(f"  unresolved (open)      : {n_unresolved}")
    if n_resolved:
        wr  = n_wins / n_resolved * 100
        roi = total_pnl / total_cost * 100 if total_cost > 0 else 0
        print(f"  win rate (if filled)   : {wr:.1f}%")
        print(f"  total hypothetical cost: ${total_cost:.2f}")
        print(f"  total hypothetical PnL : ${total_pnl:+.2f}")
        print(f"  hypothetical ROI       : {roi:+.2f}%")
        print()
        avg_pnl = total_pnl / n_resolved
        print(f"  Avg PnL per missed trade (if filled): ${avg_pnl:+.3f}")
        print()
        print("NOTE: this is OPTIMISTIC — assumes orders would have filled at the")
        print("requested limit price. In reality the orderbook moved against us, so")
        print("real fills would have been 1-3c worse per share (~10-30% reduction in PnL).")
        adj_pnl = total_pnl - (n_resolved * 0.02 * 10)  # rough 2c × ~10 shares
        print(f"  Slippage-adjusted estimate (2c penalty per trade): ${adj_pnl:+.2f}")


if __name__ == "__main__":
    main()
