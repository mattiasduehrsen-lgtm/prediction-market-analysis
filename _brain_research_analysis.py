"""
Brain research data analysis — Q3, Q4, Q5.

Q3: Regime persistence — chunked EV table.
Q4: Best vs worst chunk distinctive features.
Q5: Upper bound of regime classification value (ranging vs trending labels).
"""
import io
import sys
sys.stdout.reconfigure(encoding='utf-8')
import math
from pathlib import Path
import pandas as pd
import numpy as np

CSV = Path(r"C:\Users\home user\Desktop\prediction-market-analysis\cowork_snapshot\5m_trading\trades_v1_29_postdeploy.csv")

# Skip SSH banner lines if present
with open(CSV, 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith('position_id,'))
df = pd.read_csv(io.StringIO(''.join(lines[header_idx:])), on_bad_lines='skip')
print(f"Loaded {len(df)} rows; header at line {header_idx}")

# Filter MR-15m
mask = (df['strategy'] == 'mean_reversion') & (df['window'] == '15m')
mr = df[mask].copy()
print(f"MR-15m: {len(mr)}")

# Numerify
num_cols = ['entry_price', 'exit_price', 'take_profit', 'size_usd', 'shares',
            'pnl_usd', 'btc_pct_change_at_entry', 'cross_window_pct',
            'liquidity', 'spread_at_entry', 'price_velocity',
            'secs_remaining_at_entry']
for c in num_cols:
    if c in mr.columns:
        mr[c] = pd.to_numeric(mr[c], errors='coerce')

# Drop incomplete
mr = mr.dropna(subset=['entry_price', 'exit_price', 'take_profit', 'size_usd', 'pnl_usd', 'exit_reason', 'asset'])
print(f"After clean: {len(mr)}")

# v1.28 corrected pnl
DISCOUNT = 0.955
def corrected_pnl(row):
    sh = round((row['size_usd'] / row['entry_price']) * DISCOUNT, 2)
    exit_p = row['take_profit'] if row['exit_reason'] == 'take_profit' else row['exit_price']
    return sh * exit_p - row['size_usd']
mr['pnl_corrected'] = mr.apply(corrected_pnl, axis=1)
mr['won'] = mr['pnl_corrected'] > 0

# Sort chronologically
mr['opened_at'] = pd.to_datetime(mr['opened_at'], errors='coerce', utc=True)
mr = mr.sort_values('opened_at').reset_index(drop=True)

print(f"\nDate range: {mr['opened_at'].min()} → {mr['opened_at'].max()}")
print(f"Overall EV: ${mr['pnl_corrected'].mean():+.3f} | WR: {mr['won'].mean()*100:.1f}% | n={len(mr)}")

# ─────────────────────────────────────────────────────────────────────
# Q3 — Chunk into ~80-trade chronological bins
# ─────────────────────────────────────────────────────────────────────
print("\n" + "="*78)
print("Q3 — Regime persistence: chronological 80-trade chunks")
print("="*78)
CHUNK = 80
mr['chunk'] = mr.index // CHUNK
chunks = mr.groupby('chunk').agg(
    n=('pnl_corrected', 'size'),
    wr=('won', 'mean'),
    ev=('pnl_corrected', 'mean'),
    total=('pnl_corrected', 'sum'),
    start=('opened_at', 'min'),
    end=('opened_at', 'max'),
    tp_rate=('exit_reason', lambda s: (s == 'take_profit').mean()),
    stop_rate=('exit_reason', lambda s: s.str.contains('stop|stalled', na=False).mean()),
    btc_abs_move=('btc_pct_change_at_entry', lambda s: s.abs().mean()),
    cross_abs=('cross_window_pct', lambda s: s.abs().mean()),
)
chunks['wr'] = chunks['wr'] * 100
print(chunks.to_string(float_format=lambda v: f"{v:+.3f}" if isinstance(v, float) else str(v)))

# Persistence: corr between chunk_i EV and chunk_{i+1} EV
evs = chunks['ev'].values
if len(evs) >= 4:
    corr = np.corrcoef(evs[:-1], evs[1:])[0, 1]
    print(f"\nLag-1 chunk EV autocorrelation: {corr:+.3f}")
    print("  Interpretation: >0.3 = regimes persist; ~0 = chunk EV is independent (noise)")

# Did sign of EV persist?
signs = np.sign(evs)
flips = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
print(f"Sign flips across {len(evs)} chunks: {flips} (random would expect ~{(len(evs)-1)/2:.1f})")

# ─────────────────────────────────────────────────────────────────────
# Q4 — Best vs worst 50-trade chunks
# ─────────────────────────────────────────────────────────────────────
print("\n" + "="*78)
print("Q4 — Best vs worst 50-trade rolling windows")
print("="*78)
W = 50
roll_ev = mr['pnl_corrected'].rolling(W).mean()
best_end = roll_ev.idxmax()
worst_end = roll_ev.idxmin()
best = mr.iloc[max(0, best_end-W+1):best_end+1]
worst = mr.iloc[max(0, worst_end-W+1):worst_end+1]

def describe(name, sub):
    print(f"\n{name} ({sub['opened_at'].min()} → {sub['opened_at'].max()}):")
    print(f"  n={len(sub)} | EV=${sub['pnl_corrected'].mean():+.3f} | WR={sub['won'].mean()*100:.1f}%")
    print(f"  TP rate:        {(sub['exit_reason']=='take_profit').mean()*100:.1f}%")
    print(f"  stop/stalled:   {sub['exit_reason'].str.contains('stop|stalled', na=False).mean()*100:.1f}%")
    print(f"  asset mix:      {dict(sub['asset'].value_counts())}")
    print(f"  side mix:       {dict(sub['side'].value_counts())}")
    if 'btc_pct_change_at_entry' in sub.columns:
        v = sub['btc_pct_change_at_entry'].dropna()
        if len(v):
            print(f"  |btc_pct_change|: mean={v.abs().mean():.4f} std={v.std():.4f}")
    if 'cross_window_pct' in sub.columns:
        v = sub['cross_window_pct'].dropna()
        if len(v):
            print(f"  |cross_window|:  mean={v.abs().mean():.4f} std={v.std():.4f}")
    if 'liquidity' in sub.columns:
        v = sub['liquidity'].dropna()
        if len(v):
            print(f"  liquidity:      mean={v.mean():.0f}")
    if 'entry_price' in sub.columns:
        print(f"  entry_price:    mean={sub['entry_price'].mean():.3f}")
    if 'exit_reason' in sub.columns:
        ex = sub['exit_reason'].value_counts().head(5)
        print(f"  top exit reasons: {dict(ex)}")

describe("BEST 50-trade window", best)
describe("WORST 50-trade window", worst)

# ─────────────────────────────────────────────────────────────────────
# Q5 — Ranging vs trending label EV gap
# ─────────────────────────────────────────────────────────────────────
print("\n" + "="*78)
print("Q5 — Upper bound: ranging vs trending labels")
print("="*78)

# Multiple proxy definitions
mr_full = mr.dropna(subset=['btc_pct_change_at_entry', 'cross_window_pct']).copy()
print(f"\nSubset with btc_pct_change & cross_window: n={len(mr_full)}")

def label_test(name, ranging_mask):
    rng = mr_full[ranging_mask]
    trd = mr_full[~ranging_mask]
    n_r, n_t = len(rng), len(trd)
    ev_r = rng['pnl_corrected'].mean() if n_r else float('nan')
    ev_t = trd['pnl_corrected'].mean() if n_t else float('nan')
    wr_r = rng['won'].mean()*100 if n_r else float('nan')
    wr_t = trd['won'].mean()*100 if n_t else float('nan')
    gap = ev_r - ev_t if (n_r and n_t) else float('nan')
    print(f"\n  Proxy: {name}")
    print(f"    RANGING:  n={n_r:4d}  EV=${ev_r:+.3f}  WR={wr_r:.1f}%")
    print(f"    TRENDING: n={n_t:4d}  EV=${ev_t:+.3f}  WR={wr_t:.1f}%")
    print(f"    GAP:      ${gap:+.3f}/trade")

# Definition A: |btc_pct_change_at_entry| < 0.0015 (tight) AND |cross_window| < 0.05
label_test(
    "|btc_pct_change|<0.0015 & |cross_window|<0.0005 → ranging",
    (mr_full['btc_pct_change_at_entry'].abs() < 0.0015) & (mr_full['cross_window_pct'].abs() < 0.0005)
)
# Definition B: just btc magnitude
label_test(
    "|btc_pct_change|<median → ranging",
    mr_full['btc_pct_change_at_entry'].abs() < mr_full['btc_pct_change_at_entry'].abs().median()
)
# Definition C: just cross_window
label_test(
    "|cross_window|<median → ranging",
    mr_full['cross_window_pct'].abs() < mr_full['cross_window_pct'].abs().median()
)
# Definition D: bottom-quartile of btc_pct_change_at_entry magnitude
label_test(
    "|btc_pct_change|<25th-percentile → ranging",
    mr_full['btc_pct_change_at_entry'].abs() < mr_full['btc_pct_change_at_entry'].abs().quantile(0.25)
)
# Definition E: opposite — what if "trending" needs both signals same direction & large?
mag_ok = mr_full['btc_pct_change_at_entry'].abs() < mr_full['btc_pct_change_at_entry'].abs().quantile(0.5)
cross_ok = mr_full['cross_window_pct'].abs() < mr_full['cross_window_pct'].abs().quantile(0.5)
label_test(
    "BOTH below median (truly quiet) → ranging",
    mag_ok & cross_ok
)

# ─────────────────────────────────────────────────────────────────────
# UPPER BOUND: oracle regime classifier — perfect labelling
# ─────────────────────────────────────────────────────────────────────
print("\n— ORACLE upper bound (perfect 50/50 split keeping winners) —")
# If we could perfectly identify the +EV half: trade only the trades where pnl_corrected>0
# That's a degenerate upper bound but informative
half = mr_full.sort_values('pnl_corrected', ascending=False).head(len(mr_full)//2)
print(f"  Top-50% perfect oracle EV: ${half['pnl_corrected'].mean():+.3f}/trade")

# More realistic: the top decile of any single feature
for feat in ['btc_pct_change_at_entry', 'cross_window_pct', 'liquidity', 'spread_at_entry']:
    if feat not in mr_full.columns:
        continue
    v = mr_full[feat].abs() if 'pct' in feat or 'spread' in feat else mr_full[feat]
    mr_full[f'_q_{feat}'] = pd.qcut(v, 4, labels=False, duplicates='drop')
    g = mr_full.groupby(f'_q_{feat}')['pnl_corrected'].mean()
    print(f"  EV by {feat} quartile: " + " | ".join(f"Q{i}=${g.iloc[i]:+.2f}" for i in range(len(g))))

# ─────────────────────────────────────────────────────────────────────
# Recent-history-based regime detector — the actual brain question
# ─────────────────────────────────────────────────────────────────────
print("\n" + "="*78)
print("Q3b — Can rolling recent-WR predict next-trade EV?")
print("="*78)

# For each trade, compute prior 8-trade WR and prior 8-trade EV (within same asset)
def add_prior_window(g, n=8):
    g = g.sort_values('opened_at').reset_index(drop=True)
    g[f'prior{n}_wr']  = g['won'].shift(1).rolling(n, min_periods=n).mean()
    g[f'prior{n}_ev']  = g['pnl_corrected'].shift(1).rolling(n, min_periods=n).mean()
    return g

rolled = mr.groupby('asset', group_keys=False).apply(add_prior_window, n=8)
rolled = rolled.dropna(subset=['prior8_wr', 'prior8_ev'])
print(f"After requiring 8-trade prior window: n={len(rolled)}")

# Bin by prior WR
rolled['prior_wr_bucket'] = pd.cut(rolled['prior8_wr'], bins=[-.01, .25, .5, .75, 1.01],
                                    labels=['<25%', '25-50%', '50-75%', '>75%'])
g = rolled.groupby('prior_wr_bucket', observed=True).agg(
    n=('pnl_corrected', 'size'),
    next_ev=('pnl_corrected', 'mean'),
    next_wr=('won', lambda s: s.mean()*100),
)
print("\nNext-trade EV/WR by prior 8-trade WR bucket:")
print(g)

# Bin by prior EV
rolled['prior_ev_bucket'] = pd.cut(rolled['prior8_ev'], bins=[-100, -2, 0, 2, 100],
                                    labels=['<-$2', '-$2 to $0', '$0 to +$2', '>+$2'])
g2 = rolled.groupby('prior_ev_bucket', observed=True).agg(
    n=('pnl_corrected', 'size'),
    next_ev=('pnl_corrected', 'mean'),
    next_wr=('won', lambda s: s.mean()*100),
)
print("\nNext-trade EV/WR by prior 8-trade EV bucket:")
print(g2)

# Correlation
corr_wr = np.corrcoef(rolled['prior8_wr'], rolled['won'])[0,1]
corr_ev = np.corrcoef(rolled['prior8_ev'], rolled['pnl_corrected'])[0,1]
print(f"\nCorrelation prior8_wr → next-trade win:  {corr_wr:+.3f}")
print(f"Correlation prior8_ev → next-trade pnl:  {corr_ev:+.3f}")

# Per-asset breakout for prior_wr
print("\nPer-asset: next-trade EV by prior 8-trade WR bucket")
for asset in ['BTC', 'ETH', 'SOL']:
    sub = rolled[rolled['asset'] == asset]
    if len(sub) < 20:
        continue
    g3 = sub.groupby('prior_wr_bucket', observed=True).agg(n=('pnl_corrected','size'), next_ev=('pnl_corrected','mean'))
    print(f"  {asset}: ", dict(zip(g3.index, [f'n={r.n} ev=${r.next_ev:+.2f}' for r in g3.itertuples()])))

print("\n=== Done ===")
