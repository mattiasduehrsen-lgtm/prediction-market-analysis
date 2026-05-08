"""
Retroactive v1.28 correction analysis.

Apply the v1.28 PAPER pnl corrections to all historical PAPER trades and report
what the EV would have been with honest accounting:

  Fix 1: TP exits priced at pos.take_profit (was cur_up, typically >TP).
  Fix 2: shares = round(POSITION_SIZE/entry_price * 0.955, 2) (was no discount).

Goal: validate whether the strategy was actually positive-EV pre-v1.28 corrections,
or whether the +$0.12 EV figure was an artifact of optimistic accounting.

Run: .venv\\Scripts\\python.exe analyze_v1_28_retro.py
"""
import pandas as pd
from pathlib import Path

CSV = Path(r"C:\Users\home user\Desktop\prediction-market-analysis\cowork_snapshot\5m_trading\trades.csv")

# SSH warning lines may be at top of the file (from rsync via ssh)
# Find the real header line that starts with "position_id,"
with open(CSV, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith('position_id,'))
print(f"Header at line {header_idx}, skipping {header_idx} prefix lines")

import io
df = pd.read_csv(io.StringIO(''.join(lines[header_idx:])), on_bad_lines='skip')
print(f"Loaded {len(df)} trades")
print(f"Columns: {list(df.columns)[:15]}... total={len(df.columns)}")

# Filter to MR-15m only (the live strategy)
mask = (df['strategy'] == 'mean_reversion') & (df['window'] == '15m')
mr = df[mask].copy()
print(f"MR-15m trades: {len(mr)}")

# Required columns
needed = ['side', 'entry_price', 'exit_price', 'take_profit', 'size_usd',
          'shares', 'pnl_usd', 'exit_reason', 'asset']
missing = [c for c in needed if c not in mr.columns]
if missing:
    print(f"MISSING columns: {missing}")
    raise SystemExit(1)

# Clean — drop rows with bad numeric data
for c in ['entry_price', 'exit_price', 'take_profit', 'size_usd', 'shares', 'pnl_usd']:
    mr[c] = pd.to_numeric(mr[c], errors='coerce')
mr = mr.dropna(subset=needed)
print(f"After cleaning: {len(mr)}")

# ----- Recompute corrected pnl -----
# v1.28 share discount: PAPER over-stated shares by 1/0.955 = 4.7%
DISCOUNT = 0.955

def corrected_pnl(row):
    # v1.28 Fix 2: corrected share count
    correct_shares = round((row['size_usd'] / row['entry_price']) * DISCOUNT, 2)

    # v1.28 Fix 1: TP exits should price at take_profit, not at recorded exit_price
    # Note: in PAPER, recorded exit_price was the CHEAP-side price at exit time
    # (cur_up if UP, 1-cur_up if DOWN). For TP it was >= take_profit.
    if row['exit_reason'] == 'take_profit':
        # When the cheap side hits TP=0.60, PAPER recorded the observed price
        # (often 0.61-0.63). v1.28 prices it at exactly take_profit.
        exit_p = row['take_profit']
    else:
        exit_p = row['exit_price']

    return correct_shares * exit_p - row['size_usd']

mr['pnl_v1_28'] = mr.apply(corrected_pnl, axis=1)
mr['pnl_delta'] = mr['pnl_v1_28'] - mr['pnl_usd']

# ----- Summary by segment -----
def summarize(label, df):
    n = len(df)
    if n == 0:
        return
    wr = (df['pnl_usd'] > 0).mean() * 100
    ev_old = df['pnl_usd'].mean()
    ev_new = df['pnl_v1_28'].mean()
    delta = ev_new - ev_old
    total_old = df['pnl_usd'].sum()
    total_new = df['pnl_v1_28'].sum()
    print(f"  {label:25s} n={n:5d}  WR={wr:5.1f}%  "
          f"EV_old=${ev_old:+.3f}  EV_v1.28=${ev_new:+.3f}  "
          f"delta=${delta:+.3f}  total_old=${total_old:+.0f}  total_new=${total_new:+.0f}")

print("\n=== Overall (MR-15m) ===")
summarize("ALL", mr)

print("\n=== By asset ===")
for asset in ['BTC', 'ETH', 'SOL']:
    summarize(asset, mr[mr['asset'] == asset])

print("\n=== By side ===")
for asset in ['BTC', 'ETH', 'SOL']:
    for side in ['UP', 'DOWN']:
        sub = mr[(mr['asset'] == asset) & (mr['side'] == side)]
        if len(sub) >= 5:
            summarize(f"{asset} {side}", sub)

print("\n=== By exit_reason ===")
for reason in mr['exit_reason'].value_counts().index[:8]:
    summarize(reason, mr[mr['exit_reason'] == reason])

# Just TP wins — these are the most affected by Fix 1
tp = mr[mr['exit_reason'] == 'take_profit']
print(f"\n=== TP wins detail ===")
print(f"  count                        : {len(tp)}")
print(f"  avg recorded exit_price      : {tp['exit_price'].mean():.4f}")
print(f"  avg take_profit              : {tp['take_profit'].mean():.4f}")
print(f"  avg gap (exit - TP)          : {(tp['exit_price'] - tp['take_profit']).mean():+.4f}")
print(f"  avg PAPER over-statement     : ${tp['pnl_delta'].mean():+.3f}")

# ETH-specific deep dive (the only consistently positive segment in old analysis)
eth = mr[mr['asset'] == 'ETH']
eth_up = eth[eth['side'] == 'UP']
eth_dn = eth[eth['side'] == 'DOWN']
print(f"\n=== ETH detail ===")
print(f"  ETH ALL  v1.28 EV: ${eth['pnl_v1_28'].mean():+.3f}/trade  total: ${eth['pnl_v1_28'].sum():+.2f}")
print(f"  ETH UP   v1.28 EV: ${eth_up['pnl_v1_28'].mean():+.3f}/trade  n={len(eth_up)}")
print(f"  ETH DOWN v1.28 EV: ${eth_dn['pnl_v1_28'].mean():+.3f}/trade  n={len(eth_dn)}")

# T-stat on ETH combined post-correction
import math
n = len(eth)
mean = eth['pnl_v1_28'].mean()
std = eth['pnl_v1_28'].std()
tstat = mean / (std / math.sqrt(n))
print(f"  ETH t-stat vs zero (v1.28)   : t={tstat:+.2f}")

print("\n=== Done ===")
