"""Trace cash flow on LIVE orders since a cutoff timestamp."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
P = ROOT / "output" / "esports_fade" / "live_orders.jsonl"

# default: last 12 hours
import time
cutoff = float(sys.argv[1]) if len(sys.argv) > 1 else (time.time() - 12*3600)
print(f"Cutoff: ts >= {cutoff:.0f}  (~{(time.time()-cutoff)/3600:.1f}h ago)")

filled_buy = 0.0
n_filled = 0
sells = 0.0
n_sells = 0
cxl = 0
cxl_partial = 0.0
with open(P, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        ts = float(d.get("ts") or 0)
        if ts < cutoff:
            continue
        side = d.get("side")
        st = str(d.get("status", "")).lower()
        c = float(d.get("cost_usd") or 0)
        if side == "BUY":
            if st in ("matched", "filled"):
                filled_buy += c
                n_filled += 1
            elif st in ("canceled", "cancelled"):
                cxl += 1
                if c > 0:
                    cxl_partial += c
        elif side == "SELL":
            sells += c
            n_sells += 1

print()
print(f"BUY filled        : {n_filled}  cost ${filled_buy:.2f}")
print(f"BUY cxl-partial   : ${cxl_partial:.2f}  (partial fills inside cancelled orders)")
print(f"BUY cancelled     : {cxl}  (full cancels, $0 cost)")
print(f"SELL (manual)     : {n_sells}  proceeds ${sells:.2f}")
print()
print(f"NET cash spent    : ${filled_buy + cxl_partial - sells:+.2f}")
