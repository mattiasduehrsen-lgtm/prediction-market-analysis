"""Close out PAPER positions that got stranded during the 2-day bot outage.

The 15m crypto PAPER bot leaves a row per signal in trades_{ASSET}-15m.csv with
state=open or state=pending_exit. Normally the bot writes the close-out at
window-end. But during the 2026-05-17 to 2026-05-19 outage many positions were
never closed, leaving the PnL data understated.

This script:
  1. Finds all open / pending_exit rows in the three trades_*-15m.csv files
  2. Looks up the market's resolution via gamma-api (one batch call per asset)
  3. Computes realized PnL based on whether our `side` (UP/DOWN) won
  4. Rewrites the CSV with state=closed and pnl_usd / return_pct filled in
  5. Backs up the original CSV to .csv.bak before writing

Safe to re-run. Positions whose markets are not yet resolved are left untouched.
"""
from __future__ import annotations
import csv
import shutil
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "output" / "5m_live"
GAMMA = "https://gamma-api.polymarket.com/markets"


def fetch_resolutions(condition_ids: list[str]) -> dict[str, dict]:
    """Return {condition_id: {closed, winning_side ('UP'|'DOWN'|None), outcomePrices}}."""
    out = {}
    # Batch 25 at a time
    for i in range(0, len(condition_ids), 25):
        batch = condition_ids[i:i + 25]
        params = {"condition_ids": ",".join(batch)}
        try:
            r = requests.get(GAMMA, params=params, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"  gamma-api error: {e}")
            continue
        if not isinstance(data, list):
            continue
        for m in data:
            cid = m.get("conditionId") or m.get("condition_id")
            if not cid:
                continue
            outcomes = m.get("outcomes")
            prices = m.get("outcomePrices")
            # outcomes/prices come as JSON-encoded strings in the API response
            if isinstance(outcomes, str):
                import json as _j
                try: outcomes = _j.loads(outcomes)
                except Exception: outcomes = []
            if isinstance(prices, str):
                import json as _j
                try: prices = _j.loads(prices)
                except Exception: prices = []
            winning_side = None
            if outcomes and prices and len(outcomes) == len(prices):
                pairs = list(zip(outcomes, [float(p) for p in prices]))
                # Find decisively-resolved outcome (>= 0.99)
                winners = [o for o, p in pairs if p >= 0.99]
                if len(winners) == 1:
                    w = winners[0].upper()
                    if w in ("UP", "DOWN", "YES", "NO"):
                        # For Up/Down markets, outcome label matches our side directly.
                        winning_side = "UP" if "UP" in w or w == "YES" else "DOWN"
            out[cid] = {
                "closed":        bool(m.get("closed", False)),
                "winning_side":  winning_side,
                "outcome_prices": prices,
            }
        time.sleep(0.2)  # be polite to the API
    return out


def process_asset(asset: str) -> dict:
    path = DATA / f"trades_{asset}-15m.csv"
    if not path.exists():
        return {"asset": asset, "skipped": True}
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if not rows:
        return {"asset": asset, "skipped": True}
    header = list(rows[0].keys())

    open_rows = [r for r in rows if r.get("state") in ("open", "pending_exit")]
    if not open_rows:
        return {"asset": asset, "open": 0, "resolved": 0, "still_open": 0, "pnl": 0.0}

    cids = list({r["condition_id"] for r in open_rows if r.get("condition_id")})
    print(f"[{asset}] {len(open_rows)} open positions across {len(cids)} unique markets — fetching resolutions...")
    resolutions = fetch_resolutions(cids)

    resolved_count = 0
    still_open = 0
    total_pnl = 0.0
    for r in open_rows:
        cid = r.get("condition_id")
        info = resolutions.get(cid)
        if not info:
            still_open += 1
            continue
        if not info["closed"] and not info["winning_side"]:
            still_open += 1
            continue
        winning = info["winning_side"]
        if not winning:
            still_open += 1
            continue
        # Compute PnL
        try:
            size_usd = float(r.get("size_usd") or 0)
            shares   = float(r.get("shares") or 0)
            entry    = float(r.get("entry_price") or 0)
        except (TypeError, ValueError):
            still_open += 1
            continue
        our_side = (r.get("side") or "").upper()
        won = (our_side == winning)
        if won:
            # Shares pay $1 each
            pnl = round(shares * 1.0 - size_usd, 4)
            exit_price = 1.0
        else:
            pnl = round(-size_usd, 4)
            exit_price = 0.0
        return_pct = round((pnl / size_usd * 100), 2) if size_usd else 0
        r["state"]         = "closed"
        r["exit_price"]    = str(exit_price)
        r["exit_fee_usd"]  = r.get("exit_fee_usd") or "0.0"
        r["closed_at"]     = str(time.time())
        r["pnl_usd"]       = str(pnl)
        r["return_pct"]    = str(return_pct)
        r["resolution_side"] = winning
        r["our_side_won"]  = "True" if won else "False"
        if not r.get("exit_reason"):
            r["exit_reason"] = "stuck_position_reconciled"
        resolved_count += 1
        total_pnl += pnl

    # Write back: backup first, then rewrite
    bak = path.with_suffix(".csv.bak")
    shutil.copy2(path, bak)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    return {"asset": asset, "open": len(open_rows), "resolved": resolved_count,
            "still_open": still_open, "pnl": round(total_pnl, 2),
            "backup": str(bak)}


def main():
    print("Reconciling stuck PAPER positions across BTC / ETH / SOL ...")
    print()
    summary = []
    for asset in ("BTC", "ETH", "SOL"):
        s = process_asset(asset)
        summary.append(s)
        if s.get("skipped"):
            print(f"  {asset}: file missing, skipped")
            continue
        print(f"  {asset}: {s['open']} stuck -> {s['resolved']} resolved, "
              f"{s['still_open']} still genuinely open, PnL ${s['pnl']:+.2f}")
        if s.get("backup"):
            print(f"     backup: {Path(s['backup']).name}")
    print()
    total_resolved = sum(s.get("resolved", 0) for s in summary)
    total_pnl = sum(s.get("pnl", 0) for s in summary)
    total_still = sum(s.get("still_open", 0) for s in summary)
    print(f"=== Done. {total_resolved} positions reconciled, ${total_pnl:+.2f} PnL added to PAPER ledger. "
          f"{total_still} still genuinely open. ===")


if __name__ == "__main__":
    main()
