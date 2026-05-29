"""Where does the latency go? Break the fade pipeline into segments and
report percentiles, so we know whether a VPS (network) or a different data
source (indexer lag) is the right fix.

Pipeline segments (all seconds):
  A. their_fill_ts  -> signal_seen_at   = indexer lag + our poll interval
                                           (time from THEIR on-chain fill to us SEEING it)
  B. signal_seen_at -> submit_at        = our processing (wallet check, market lookup)
  C. submit_at      -> sign_at          = order signing (local crypto)
  D. sign_at        -> response_at       = CLOB POST round-trip (network — VPS helps here)
  total: their_fill_ts -> response_at
"""
from __future__ import annotations
import json
from pathlib import Path
import statistics as st

ROOT = Path(__file__).resolve().parents[1]
ORDERS = ROOT / "output" / "esports_fade" / "live_orders.jsonl"
EVENTS = ROOT / "output" / "esports_fade" / "fade_events.jsonl"

def pct(xs, p):
    if not xs: return float("nan")
    xs = sorted(xs); k = (len(xs)-1)*p/100
    f = int(k); c = min(f+1, len(xs)-1)
    return xs[f] + (xs[c]-xs[f])*(k-f)

def report(name, xs, unit="s"):
    xs = [x for x in xs if x is not None]
    if not xs:
        print(f"  {name:<34} (no data)")
        return
    print(f"  {name:<34} n={len(xs):>4}  "
          f"p50={pct(xs,50):>7.2f}{unit}  p90={pct(xs,90):>7.2f}{unit}  "
          f"p99={pct(xs,99):>7.2f}{unit}  max={max(xs):>7.2f}{unit}")

def load_jsonl(p):
    out=[]
    if not p.exists(): return out
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line=line.strip()
            if not line: continue
            try: out.append(json.loads(line))
            except Exception: pass
    return out

orders = load_jsonl(ORDERS)
# Only rows that actually posted (have the latency fields)
placed = [o for o in orders if o.get("submit_at") and o.get("their_fill_ts")]
print("="*92)
print(f" LATENCY BREAKDOWN — {len(placed)} placed orders with full instrumentation")
print("="*92)

A=[]; B=[]; C=[]; D=[]; total=[]
for o in placed:
    tf = float(o.get("their_fill_ts") or 0)
    ss = float(o.get("signal_seen_at") or 0)
    su = float(o.get("submit_at") or 0)
    sg = float(o.get("sign_at") or 0)
    rs = float(o.get("response_at") or o.get("final_at") or 0)
    if tf and ss: A.append(ss-tf)
    if ss and su: B.append(su-ss)
    if su and sg: C.append(sg-su)
    if sg and rs: D.append(rs-sg)
    if tf and rs: total.append(rs-tf)

print("\n[A] their on-chain fill -> we SEE it (indexer lag + poll)")
report("A: their_fill -> signal_seen", A)
print("\n[B] we see it -> we submit (our processing)")
report("B: signal_seen -> submit", B)
print("\n[C] submit -> signed (local crypto)")
report("C: submit -> sign", C)
print("\n[D] signed -> CLOB responded (NETWORK round-trip — VPS helps here)")
report("D: sign -> response", D)
print("\n[TOTAL] their fill -> CLOB responded")
report("TOTAL", total)

# What fraction of total is each segment (at p50)?
print("\n" + "="*92)
print(" WHERE THE TIME GOES (median contribution)")
print("="*92)
segs = {"A indexer+poll": A, "B processing": B, "C signing": C, "D network": D}
med = {k: pct(v,50) for k,v in segs.items() if v}
s = sum(med.values()) or 1
for k,v in med.items():
    bar = "#"*int(v/s*50)
    print(f"  {k:<18} {v:>7.2f}s  {v/s*100:>5.1f}%  {bar}")

# Stale skips — signals we saw too late to act on
events = load_jsonl(EVENTS)
stale = [e for e in events if e.get("type")=="skip_stale_target_trade"]
ages = [float(e.get("age_s") or 0) for e in stale]
print("\n" + "="*92)
print(f" STALE SIGNALS SKIPPED (saw them after MAX_TRADE_AGE_SECONDS): {len(stale)}")
print("="*92)
if ages:
    report("stale age when skipped", ages)
    print(f"  These are signals we MISSED entirely due to latency.")
