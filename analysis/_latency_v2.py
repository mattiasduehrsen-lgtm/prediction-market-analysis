"""Latency from fade_events.jsonl: signal_lag (segment A) for ALL fade signals,
plus the full A/B/C/D breakdown from live_order_placed events.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "output" / "esports_fade" / "fade_events.jsonl"

def pct(xs,p):
    if not xs: return float("nan")
    xs=sorted(xs); k=(len(xs)-1)*p/100; f=int(k); c=min(f+1,len(xs)-1)
    return xs[f]+(xs[c]-xs[f])*(k-f)
def rep(name,xs,u="s"):
    xs=[x for x in xs if x is not None]
    if not xs: print(f"  {name:<32} (no data)"); return
    print(f"  {name:<32} n={len(xs):>4}  p50={pct(xs,50):>7.2f}{u}  p90={pct(xs,90):>7.2f}{u}  p99={pct(xs,99):>7.2f}{u}  max={max(xs):>7.1f}{u}")

ev=[]
with EVENTS.open(encoding="utf-8") as fh:
    for line in fh:
        line=line.strip()
        if not line: continue
        try: ev.append(json.loads(line))
        except Exception: pass

# Segment A: signal_lag_s on every fade_signal (their_fill -> we saw it)
sig=[e for e in ev if e.get("type")=="fade_signal"]
lagA=[float(e.get("signal_lag_s")) for e in sig if e.get("signal_lag_s") is not None]
print("="*92)
print(f" SEGMENT A — their on-chain fill -> we SEE it  (from {len(lagA)} fade signals)")
print("="*92)
rep("A: indexer lag + poll", lagA)

# Full breakdown from live_order_placed
op=[e for e in ev if e.get("type")=="live_order_placed"]
def seg(a,b):
    out=[]
    for e in op:
        x=e.get(a); y=e.get(b)
        if x and y: out.append(float(y)-float(x))
    return out
print("\n" + "="*92)
print(f" FULL PIPELINE — from {len(op)} live_order_placed events")
print("="*92)
rep("A: their_fill -> signal_seen", seg("their_fill_ts","signal_seen_at"))
rep("B: signal_seen -> submit",     seg("signal_seen_at","submit_at"))
rep("C: submit -> sign",            seg("submit_at","sign_at"))
rep("D: sign -> response (NETWORK)",seg("sign_at","response_at"))
rep("TOTAL their_fill -> response", seg("their_fill_ts","response_at"))

# Pre-computed lag fields if present
lps=[float(e["lag_post_s"]) for e in op if e.get("lag_post_s") is not None]
lss=[float(e["lag_sign_s"]) for e in op if e.get("lag_sign_s") is not None]
print("\n  (pre-computed fields)")
rep("  lag_sign_s",  lss)
rep("  lag_post_s (network POST)", lps)

# Stale skips
stale=[e for e in ev if e.get("type")=="skip_stale_target_trade"]
ages=[float(e.get("age_s") or 0) for e in stale]
acted=len(sig); missed=len(stale)
print("\n" + "="*92)
print(" ACTED vs MISSED (latency cost)")
print("="*92)
print(f"  fade signals ACTED on : {acted}")
print(f"  stale signals MISSED  : {missed}  ({missed/(acted+missed)*100:.0f}% of all target signals)")
rep("  age of missed signals", ages)
# How many ACTED signals were already old?
old_acted=[x for x in lagA if x>60]
print(f"  ACTED signals >60s old: {len(old_acted)} ({len(old_acted)/max(len(lagA),1)*100:.0f}%)")
old120=[x for x in lagA if x>120]
print(f"  ACTED signals >120s old: {len(old120)} ({len(old120)/max(len(lagA),1)*100:.0f}%)")
