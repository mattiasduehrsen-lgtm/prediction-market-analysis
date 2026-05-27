"""Scan live orders for any markets where we hold BOTH SIDES (guaranteed loss).

Reads both esports and sports live_orders.jsonl, groups matched BUYs by
(condition_id, outcome), and flags any market where we have matched BUYs
on more than one outcome.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]

def scan(bot_name: str, orders_path: Path):
    if not orders_path.exists():
        print(f"[{bot_name}] no orders file at {orders_path}")
        return
    # Build set of resolved cids from live_results.csv so we don't include
    # markets that have already settled (we got the payout, exposure is moot).
    resolved_cids: set[str] = set()
    results_path = orders_path.with_name("live_results.csv")
    if results_path.exists():
        import csv as _csv
        with results_path.open(encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                if r.get("status") in ("WIN", "LOSS", "TP_SOLD", "TP_LOSS"):
                    cid = r.get("fade_condition", "")
                    if cid:
                        resolved_cids.add(cid)
    # cid -> {outcome -> [(ts, shares, cost)]}
    positions = defaultdict(lambda: defaultdict(list))
    slug_for_cid = {}
    with orders_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if str(o.get("side","BUY")).upper() != "BUY": continue
            if str(o.get("status","")).lower() != "matched": continue
            shares = float(o.get("shares") or 0)
            cost = float(o.get("cost_usd") or 0)
            if shares <= 0: continue
            cid = o.get("fade_condition","")
            outcome = o.get("our_outcome","")
            if not cid or not outcome: continue
            if cid in resolved_cids: continue  # already settled, ignore
            positions[cid][outcome].append((o.get("ts",0), shares, cost))
            if cid not in slug_for_cid:
                slug_for_cid[cid] = o.get("fade_slug","")

    # Also subtract any matched SELLs by outcome to know net holding
    # (we close TP_SOLD positions explicitly)
    sells = defaultdict(lambda: defaultdict(float))  # cid -> outcome -> shares_sold
    with orders_path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                o = json.loads(line.strip())
            except Exception:
                continue
            if str(o.get("side","BUY")).upper() != "SELL": continue
            if str(o.get("status","")).lower() != "matched": continue
            cid = o.get("fade_condition","")
            outcome = o.get("our_outcome","")
            sells[cid][outcome] += float(o.get("shares") or 0)

    print(f"\n===== {bot_name.upper()} =====")
    flagged = 0
    for cid, by_outcome in positions.items():
        # Compute net shares per outcome
        net = {}
        for outcome, fills in by_outcome.items():
            total_bought = sum(s for (_, s, _) in fills)
            total_cost   = sum(c for (_, _, c) in fills)
            sold = sells[cid].get(outcome, 0.0)
            net_shares = total_bought - sold
            if net_shares > 0.01:
                net[outcome] = (net_shares, total_cost)
        if len(net) >= 2:
            flagged += 1
            slug = slug_for_cid.get(cid, cid[:20])
            max_payout = max(sh for (sh, _) in net.values())
            total_cost = sum(c for (_, c) in net.values())
            worst_loss = max_payout - total_cost  # if best-payout side wins
            # If neither side wins... but in binary markets exactly one resolves YES
            # so we'll always get the max-payout side's value or one of the others'.
            print(f"  !! DUAL POSITION: {slug}")
            for outcome, (sh, c) in sorted(net.items()):
                print(f"      {outcome:>15}: {sh:>6.2f} shares  cost ${c:>6.2f}")
            print(f"      total cost: ${total_cost:.2f}")
            print(f"      best-case (max payout): ${max_payout:.2f}  -> "
                  f"PnL ${max_payout - total_cost:+.2f}")
            # Worst case is the SMALLEST-payout side winning
            worst_payout = min(sh for (sh, _) in net.values())
            print(f"      worst-case (min payout): ${worst_payout:.2f}  -> "
                  f"PnL ${worst_payout - total_cost:+.2f}")
            print()
    if flagged == 0:
        print(f"  OK no dual-side positions ({len(positions)} markets scanned)")
    else:
        print(f"  Total: {flagged} dual-side markets")

if __name__ == "__main__":
    scan("esports", ROOT / "output" / "esports_fade" / "live_orders.jsonl")
    scan("sports",  ROOT / "output" / "sports_fade"  / "live_orders.jsonl")
