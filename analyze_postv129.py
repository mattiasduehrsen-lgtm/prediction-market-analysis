"""
Post-v1.29 PAPER trade analysis.

Pull fresh trades.csv (copied from laptop), filter to:
  - MR-15m only
  - opened_at >= 2026-05-07 20:46 UTC (when PAPER came back up after v1.28 deploy)

Report:
  - n by asset/side
  - WR / EV with the v1.28 corrections ALREADY APPLIED in the data
    (shares column is now discounted; TP exits price at exact take_profit)
  - Compare against the corrected v1.28 retroactive baseline
  - Specifically: how is SOL UP doing on fresh data?
"""
import io
import math
from pathlib import Path

import pandas as pd

CSV = Path(r"C:\Users\home user\Desktop\prediction-market-analysis\cowork_snapshot\5m_trading\trades_v1_29_postdeploy.csv")

with open(CSV, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith('position_id,'))
df = pd.read_csv(io.StringIO(''.join(lines[header_idx:])), on_bad_lines='skip')
print(f"Loaded {len(df)} total trades from fresh trades.csv")

# Filter to MR-15m
mr = df[(df['strategy'] == 'mean_reversion') & (df['window'] == '15m')].copy()
for c in ['entry_price', 'exit_price', 'take_profit', 'size_usd', 'shares', 'pnl_usd', 'opened_at']:
    mr[c] = pd.to_numeric(mr[c], errors='coerce')
mr = mr.dropna(subset=['entry_price', 'exit_price', 'pnl_usd', 'opened_at'])

# Convert opened_at (epoch seconds) to datetime
mr['opened_dt'] = pd.to_datetime(mr['opened_at'], unit='s', utc=True)

# Cutoff: 2026-05-07 20:46 UTC = epoch 1778187960 (when PAPER came back up after the
# 24h dead window post-v1.28 deploy). All trades after this used the v1.28 fixes.
CUTOFF_EPOCH = 1778187960
post = mr[mr['opened_at'] >= CUTOFF_EPOCH].copy()
pre = mr[mr['opened_at'] < CUTOFF_EPOCH].copy()

print(f"\nMR-15m total: {len(mr)}")
print(f"  pre-v1.28 (old accounting):   n={len(pre)}")
print(f"  post-v1.28 (corrected):       n={len(post)}")
print(f"\nDate range of post-v1.28 trades:")
if len(post):
    print(f"  earliest: {post['opened_dt'].min()}")
    print(f"  latest:   {post['opened_dt'].max()}")

# Per-asset/side breakdown of post-v1.28 trades (these are honest accounting)
def summarize(label, df):
    n = len(df)
    if n == 0:
        return f"  {label:25s} n={n:5d}  (no trades)"
    wr = (df['pnl_usd'] > 0).mean() * 100
    ev = df['pnl_usd'].mean()
    total = df['pnl_usd'].sum()
    sd = df['pnl_usd'].std() if n > 1 else float('nan')
    se = sd / math.sqrt(n) if n > 1 else float('nan')
    t = ev / se if se and se > 0 else float('nan')
    return (f"  {label:25s} n={n:5d}  WR={wr:5.1f}%  "
            f"EV=${ev:+7.3f}  total=${total:+7.2f}  t={t:+5.2f}")

print("\n=== POST-v1.28 TRADES (honest accounting) ===")
print(summarize("ALL MR-15m", post))
print()
for asset in ['BTC', 'ETH', 'SOL']:
    print(summarize(f"{asset} ALL", post[post['asset'] == asset]))
    for side in ['UP', 'DOWN']:
        sub = post[(post['asset'] == asset) & (post['side'] == side)]
        if len(sub) > 0:
            print(summarize(f"  {asset} {side}", sub))
    print()

# Compare: post-v1.28 SOL UP vs the v1.28 retroactive SOL UP (n=74, EV +$0.53)
sol_up_post = post[(post['asset'] == 'SOL') & (post['side'] == 'UP')]
sol_up_pre  = pre[(pre['asset'] == 'SOL') & (pre['side'] == 'UP')]

print("=== SOL UP — pre vs post v1.28 ===")
if len(sol_up_pre):
    print(summarize("pre-v1.28 SOL UP", sol_up_pre))
print(summarize("post-v1.28 SOL UP", sol_up_post))

# Decision threshold: was the plan "wait until SOL UP n>200" — what's our current total?
total_sol_up = len(mr[(mr['asset'] == 'SOL') & (mr['side'] == 'UP')])
print(f"\nTotal SOL UP trades all-time: {total_sol_up}  (target was 200+)")

# Exit reason breakdown for post-v1.28
print("\n=== POST-v1.28 by exit_reason ===")
for r in post['exit_reason'].value_counts().index:
    print(summarize(r, post[post['exit_reason'] == r]))

# Show the actual trades to look at them
print("\n=== Last 10 post-v1.28 trades ===")
cols = ['opened_dt', 'asset', 'side', 'entry_price', 'shares', 'exit_price', 'exit_reason', 'pnl_usd']
print(post[cols].tail(10).to_string(index=False))
