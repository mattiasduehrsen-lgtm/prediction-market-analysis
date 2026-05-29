import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
d = json.loads((ROOT/"cowork_snapshot"/"esports"/"fade_targets.json").read_text(encoding="utf-8"))
meta = d.get("target_meta") or []
print(f"LIVE subset: {len(d.get('target_wallets',[]))} wallets, {len(meta)} meta rows")
print("\nFirst 12 by current ranking (sorted by absolute pnl):")
print(f"  {'wallet':<16} {'trades':>6} {'wr':>6} {'roi':>8} {'pnl':>9}")
for m in meta[:12]:
    print(f"  {m['proxyWallet'][:14]:<16} {m['trades']:>6} {m.get('wr',0):>6.1f} "
          f"{m.get('roi',0):>8.1f} {m.get('pnl',0):>9.2f}")

# The toxic wallet
for m in meta:
    if m["proxyWallet"].startswith("0x47138dc1"):
        print(f"\nTOXIC WALLET 0x47138dc1:")
        print(f"  trades={m['trades']} wr={m.get('wr')}% roi={m.get('roi')}% pnl=${m.get('pnl')}")
        break

# Distribution: how many live-subset wallets have roi worse than thresholds
import statistics
rois = [m.get("roi",0) for m in meta]
trades = [m.get("trades",0) for m in meta]
print(f"\nLIVE subset ROI distribution:")
for thr in [-5,-10,-15,-20,-30]:
    print(f"  ROI < {thr}%: {sum(1 for r in rois if r<thr)} wallets")
print(f"  median ROI: {statistics.median(rois):.1f}%   median trades: {statistics.median(trades):.0f}")
print(f"  wallets with trades>100 (high volume): {sum(1 for t in trades if t>100)}")
