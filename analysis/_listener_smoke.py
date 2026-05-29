"""Smoke test: run OnChainListener against ALL recent wallets for ~40s to prove
it connects, detects TransferSingles, decodes, and reports latency. Uses a
broad wallet set (not just our 300) so we actually catch some events fast.
No orders — just prints what it would emit.
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from onchain_listener import OnChainListener

ES_DIR = ROOT / "cowork_snapshot" / "esports"

# Build token index (all esports tokens)
idx = {}
df = pd.read_parquet(ES_DIR/"clob_esports_markets.parquet", columns=["condition_id","tokens","slug"])
for _, row in df.iterrows():
    try:
        for t in row["tokens"]:
            if t.get("token_id") and t.get("outcome"):
                idx[str(t["token_id"])] = (row["condition_id"], t["outcome"], row.get("slug") or "")
    except TypeError: pass
print(f"token index: {len(idx)}")

# Use the PAPER target set (wider, 666) to maximize chance of catching events
import json as _j
paper = ES_DIR / "fade_targets_paper.json"
wallets = set()
if paper.exists():
    wallets = set(w.lower() for w in _j.loads(paper.read_text())["target_wallets"])
print(f"watching {len(wallets)} wallets for 45s...")

emitted = []
def on_sig(t):
    emitted.append(t)
    print(f"  EMIT lag={t['_detect_lag_s']}s {t['side']} {t['outcome'][:18]} @{t['price']} "
          f"sh={t['size']} slug={t['slug'][:30]}")

lis = OnChainListener(wallets, idx, on_sig, log=lambda m: print(m))
lis.start()
t0=time.time()
while time.time()-t0 < 45:
    time.sleep(3)
    print(f"  ...t={time.time()-t0:.0f}s conn={lis.connected} detected={lis.n_detected} "
          f"emitted={lis.n_emitted} dropped={lis.n_dropped}")
lis.stop()
print(f"\nDONE. detected={lis.n_detected} emitted={lis.n_emitted} dropped={lis.n_dropped}")
print(f"emitted {len(emitted)} signals")
