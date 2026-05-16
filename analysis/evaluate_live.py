"""
Evaluate realized PnL on LIVE orders placed by esports_fade_bot.

Counterpart to evaluate_paper.py — same logic but reads live_orders.jsonl
(one JSON line per posted CLOB order). Also writes live_daily_pnl.json
which the bot reads on each heartbeat to update self.daily_pnl, enabling
the DAILY_LOSS_CAP to actually fire.

Inputs:
  output/esports_fade/live_orders.jsonl  — each line = one posted order

Outputs:
  output/esports_fade/live_results.csv   — per-order WIN/LOSS/UNRESOLVED + PnL
  output/esports_fade/live_daily_pnl.json — {date, realized_pnl_usd, n_resolved, n_open}

Usage:
  .venv\\Scripts\\python.exe analysis\\evaluate_live.py
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT  = ROOT / "output" / "esports_fade"
ORDERS_PATH    = OUT / "live_orders.jsonl"
RESULTS_PATH   = OUT / "live_results.csv"
DAILY_PNL_PATH = OUT / "live_daily_pnl.json"

CACHE: dict[str, dict] = {}
SESSION = requests.Session()


def fetch_market(cid: str) -> dict | None:
    if cid in CACHE:
        return CACHE[cid]
    try:
        r = SESSION.get(f"https://clob.polymarket.com/markets/{cid}", timeout=8)
        if r.status_code != 200:
            return None
        j = r.json()
        CACHE[cid] = j
        return j
    except Exception:
        return None


def winning_outcome(mkt: dict) -> str | None:
    if not mkt or not mkt.get("closed"):
        return None
    for t in mkt.get("tokens", []) or []:
        if t.get("winner"):
            return t.get("outcome")
    return None


def main():
    if not ORDERS_PATH.exists():
        print(f"No live orders file at {ORDERS_PATH}")
        # Still write an empty daily PnL so the bot has something fresh to read.
        _write_daily({"date": str(datetime.now(timezone.utc).date()),
                      "realized_pnl_usd": 0.0, "n_resolved": 0, "n_open": 0,
                      "generated_at": time.time()})
        return

    orders = []
    with ORDERS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                orders.append(json.loads(line))
            except Exception:
                continue
    print(f"Loaded {len(orders):,} live orders")

    cids = sorted({o.get("fade_condition") for o in orders if o.get("fade_condition")})
    print(f"Unique markets to resolve: {len(cids)}")
    for i, cid in enumerate(cids):
        fetch_market(cid)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(cids)}")
        time.sleep(0.05)

    today_str = str(datetime.now(timezone.utc).date())
    today_pnl = 0.0
    today_resolved = 0
    today_open = 0

    out_rows = []
    n_resolved = 0
    n_wins = 0
    total_pnl = 0.0
    total_cost = 0.0

    for o in orders:
        cid    = o.get("fade_condition") or ""
        our_o  = o.get("our_outcome") or ""
        price  = float(o.get("price") or 0)
        shares = float(o.get("shares") or 0)
        cost   = price * shares          # actual $ spent on this order
        ts     = float(o.get("ts") or 0)

        mkt    = CACHE.get(cid)
        winner = winning_outcome(mkt) if mkt else None

        is_today = False
        if ts:
            is_today = str(datetime.fromtimestamp(ts, tz=timezone.utc).date()) == today_str

        if winner is None:
            out_rows.append({**o, "status": "UNRESOLVED", "realized_pnl": "",
                             "cost_usd": round(cost, 4)})
            if is_today:
                today_open += 1
            continue

        n_resolved += 1
        if winner == our_o:
            pnl = shares - cost          # each winning share pays $1
            n_wins += 1
        else:
            pnl = -cost
        total_pnl  += pnl
        total_cost += cost

        if is_today:
            today_resolved += 1
            today_pnl += pnl

        out_rows.append({**o, "status": "WIN" if pnl > 0 else "LOSS",
                         "realized_pnl": round(pnl, 4),
                         "cost_usd": round(cost, 4)})

    # Atomic write of per-order results
    if out_rows:
        # Stable column ordering — union of all keys
        cols_set = set()
        for r in out_rows:
            cols_set.update(r.keys())
        # Put status/pnl/cost columns at the end for readability
        tail_cols = ["status", "realized_pnl", "cost_usd"]
        head_cols = [c for c in out_rows[0].keys() if c not in tail_cols]
        cols = head_cols + [c for c in tail_cols if c in cols_set]

        tmp = RESULTS_PATH.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for x in out_rows:
                w.writerow({c: x.get(c, "") for c in cols})
        os.replace(tmp, RESULTS_PATH)
        print(f"\nWrote per-order results: {RESULTS_PATH}")

    # Daily PnL snapshot — bot reads this for its DAILY_LOSS_CAP guard
    _write_daily({
        "date":             today_str,
        "realized_pnl_usd": round(today_pnl, 4),
        "n_resolved":       today_resolved,
        "n_open":           today_open,
        "generated_at":     time.time(),
    })

    print("\n" + "=" * 60)
    print("LIVE REALIZED PNL SUMMARY")
    print("=" * 60)
    print(f"  Total orders        : {len(orders):,}")
    print(f"  Resolved (all-time) : {n_resolved:,}  ({n_wins} wins)")
    print(f"  PnL (all-time)      : ${total_pnl:+,.2f}  on ${total_cost:,.2f} cost")
    print(f"  ROI (all-time)      : {(total_pnl/total_cost*100 if total_cost else 0):+.2f}%")
    print()
    print(f"  TODAY ({today_str})")
    print(f"    resolved : {today_resolved}")
    print(f"    open     : {today_open}")
    print(f"    PnL      : ${today_pnl:+,.2f}")
    print()


def _write_daily(d: dict):
    tmp = DAILY_PNL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, DAILY_PNL_PATH)


if __name__ == "__main__":
    main()
