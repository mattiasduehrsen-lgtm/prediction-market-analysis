"""How often have we held both sides of the same market in LIVE history?"""
import csv
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent
f = ROOT / "output" / "esports_fade" / "live_results.csv"

# Map condition_id -> set of our_outcomes we've taken positions in
by_market = defaultdict(set)
losses = defaultdict(list)
with f.open(encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if str(r.get("side","BUY")).upper() == "SELL": continue
        cid = r.get("fade_condition") or r.get("conditionId") or ""
        o = r.get("our_outcome") or ""
        if not cid or not o: continue
        by_market[cid].add(o)
        losses[cid].append((o, r.get("status",""), float(r.get("realized_pnl") or 0),
                             float(r.get("cost_usd") or 0), r.get("fade_slug","")))

# Markets with 2+ different our_outcomes = bug occurrences
dual = {cid: outs for cid, outs in by_market.items() if len(outs) >= 2}
print(f"Markets where we took multiple opposite-side positions: {len(dual)}")
print()
total_locked_in_loss = 0
for cid, outs in dual.items():
    print(f"  cid={cid[:14]}... outcomes={sorted(outs)}")
    cost_sum = 0
    for o, status, pnl, cost, slug in losses[cid]:
        cost_sum += cost
        print(f"    {o[:18]:<18} status={status:<8} cost=${cost:>5.2f} pnl=${pnl:>+6.2f}  slug={slug[:35]}")
    total_locked_in_loss += cost_sum - 10  # rough estimate: guaranteed payout ~$10 per side
print()
print(f"Approximate locked-in loss from this bug historically: ~${total_locked_in_loss:.2f}")
