"""
Phase 2A — partial microstructure ML on existing trades.csv columns.

Adds bid_depth, ask_depth, clob_midpoint_trend, book_imbalance, depth_ratio
to the feature set from the prior ML test (which got AUC 0.496). If these
historical microstructure columns contain signal, AUC should now meaningfully
beat chance.

Run after Phase 2B (full snapshot data) for the more comprehensive test, but
this gives an early read NOW.
"""
from __future__ import annotations
import csv, io, math
from pathlib import Path

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit

ROOT = Path(__file__).resolve().parents[1]
CSV  = ROOT / "cowork_snapshot" / "5m_trading" / "trades.csv"
if not CSV.exists():
    CSV = ROOT / "output" / "5m_trading" / "trades.csv"

with open(CSV, "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()
header_idx = next(i for i, l in enumerate(lines) if l.startswith("position_id,"))
df = pd.read_csv(io.StringIO("".join(lines[header_idx:])), on_bad_lines="skip")
df = df[(df["strategy"] == "mean_reversion") & (df["window"] == "15m")].copy()
print(f"Loaded {len(df)} MR-15m trades")

# v1.28 corrected pnl
DISC = 0.955
def cpnl(r):
    try:
        sp = float(r["size_usd"]); ep = float(r["entry_price"])
        if ep <= 0: return float(r.get("pnl_usd", 0) or 0)
        sh = round(sp/ep*DISC, 2)
        xp = float(r["take_profit"]) if r.get("exit_reason") == "take_profit" else float(r["exit_price"])
        return sh*xp - sp
    except Exception:
        return float(r.get("pnl_usd", 0) or 0)
df["pnl_corr"] = df.apply(cpnl, axis=1)
df["target"]   = (df["pnl_corr"] > 0).astype(int)
df = df.sort_values("opened_at").reset_index(drop=True)

# Feature set: old 17 + new microstructure
features = [
    "entry_price", "secs_remaining_at_entry", "btc_pct_change_at_entry",
    "up_price_at_window_start", "liquidity", "spread_at_entry",
    "price_60s_before_entry", "price_30s_before_entry", "price_velocity",
    "cross_window_pct",
    # NEW microstructure columns:
    "bid_depth_at_entry", "ask_depth_at_entry", "clob_midpoint_trend_60s",
]
have = [c for c in features if c in df.columns]
print(f"Features available: {len(have)}/{len(features)}: {have}")
new_micro = [c for c in have if c in ("bid_depth_at_entry","ask_depth_at_entry","clob_midpoint_trend_60s")]
print(f"  NEW microstructure cols in dataset: {new_micro}")

# Convert + drop NaNs
for c in have:
    df[c] = pd.to_numeric(df[c], errors="coerce")
df = df.dropna(subset=have).reset_index(drop=True)

# Add derived: book_imbalance, depth_ratio
if "bid_depth_at_entry" in have and "ask_depth_at_entry" in have:
    total = df["bid_depth_at_entry"] + df["ask_depth_at_entry"]
    df["book_imbalance"] = (df["bid_depth_at_entry"] / total).fillna(0.5)
    df["depth_ratio"]    = (df["bid_depth_at_entry"] / (df["ask_depth_at_entry"] + 1)).clip(0, 100)
    have += ["book_imbalance", "depth_ratio"]

# Asset/side one-hots
for a in ("BTC","ETH","SOL"):
    df[f"is_{a}"] = (df["asset"].str.upper() == a).astype(int)
    have.append(f"is_{a}")
df["is_UP"] = (df["side"].str.upper() == "UP").astype(int)
have.append("is_UP")

print(f"\nFinal feature count: {len(have)}; n={len(df)}")
X = df[have].values
y = df["target"].values
pnl = df["pnl_corr"].values

# 5-fold time-series CV
tscv = TimeSeriesSplit(n_splits=5)
fold_aucs = []
all_proba = [None]*len(df)
for fold, (tr, te) in enumerate(tscv.split(X), 1):
    m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=20)
    m.fit(X[tr], y[tr])
    proba = m.predict_proba(X[te])[:, 1]
    for i, idx in enumerate(te):
        all_proba[idx] = proba[i]
    from sklearn.metrics import roc_auc_score
    try:
        auc = roc_auc_score(y[te], proba)
    except ValueError:
        auc = float("nan")
    fold_aucs.append(auc)
    print(f"  fold {fold}: AUC={auc:.3f}  n_test={len(te)}")
mean_auc = sum(a for a in fold_aucs if not math.isnan(a)) / len([a for a in fold_aucs if not math.isnan(a)])
print(f"\nMean AUC: {mean_auc:.3f}  (prior test with old features: 0.496)")

# Threshold sweep with OOF predictions
oof_idx = [i for i,p in enumerate(all_proba) if p is not None]
oof_proba = [all_proba[i] for i in oof_idx]
oof_pnl   = [pnl[i] for i in oof_idx]
baseline_ev = sum(oof_pnl) / len(oof_pnl)
print(f"\nBaseline OOF EV: ${baseline_ev:+.3f}  WR={sum(1 for p in oof_pnl if p>0)/len(oof_pnl)*100:.1f}%")

print("\nthreshold | n_kept | WR | mean_pnl | vs baseline")
for thr in (0.45, 0.50, 0.55, 0.60, 0.65):
    kept_pnl = [oof_pnl[i] for i,p in enumerate(oof_proba) if p >= thr]
    if not kept_pnl: continue
    wr = sum(1 for p in kept_pnl if p>0) / len(kept_pnl) * 100
    ev = sum(kept_pnl) / len(kept_pnl)
    delta = ev - baseline_ev
    flag = "  <-- MEANINGFUL" if (delta >= 0.50 and len(kept_pnl) > 30) else ""
    print(f"  {thr:.2f}   |  {len(kept_pnl):4d}  | {wr:5.1f}% | ${ev:+7.3f}  | ${delta:+.3f}{flag}")

# Verdict
print("\n=== Verdict ===")
if mean_auc >= 0.58:
    print(f"  AUC {mean_auc:.3f} >= 0.58 — real signal in microstructure features.")
    print("  -> Phase 3: deploy filter using best threshold")
elif mean_auc >= 0.53:
    print(f"  AUC {mean_auc:.3f} in 0.53-0.58 — weak signal, ambiguous.")
    print("  -> wait for full Phase 2B with brand-new microstructure CSV before deciding")
else:
    print(f"  AUC {mean_auc:.3f} < 0.53 — no signal in these microstructure cols either.")
    print("  -> still wait for Phase 2B (book_imbalance / multi-window flow features are new)")
