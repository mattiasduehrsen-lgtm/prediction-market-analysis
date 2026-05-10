"""
ML feature exploration on PAPER MR-15m trades with v1.28 corrections.
"""
import io
import math
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score, recall_score
from sklearn.inspection import permutation_importance

ROOT = Path(r"C:\Users\home user\Desktop\prediction-market-analysis")
CSV = ROOT / "cowork_snapshot" / "5m_trading" / "trades_v1_29_postdeploy.csv"
DISCOUNT = 0.955

# ----- Load -----
with open(CSV, "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()
hdr = next(i for i, l in enumerate(lines) if l.startswith("position_id,"))
df = pd.read_csv(io.StringIO("".join(lines[hdr:])), on_bad_lines="skip")
print(f"Loaded {len(df)} rows")

# Filter MR-15m
mask = (df["strategy"] == "mean_reversion") & (df["window"] == "15m")
mr = df[mask].copy()
print(f"MR-15m: {len(mr)}")

# Numeric coercion
num_cols = [
    "entry_price", "take_profit", "size_usd", "shares", "exit_price",
    "secs_remaining_at_entry", "btc_pct_change_at_entry", "up_price_at_window_start",
    "liquidity", "price_60s_before_entry", "price_30s_before_entry", "price_velocity",
    "cross_window_pct", "spread_at_entry", "opened_at", "pnl_usd",
]
for c in num_cols:
    if c in mr.columns:
        mr[c] = pd.to_numeric(mr[c], errors="coerce")

# Drop rows missing critical fields for pnl correction
mr = mr.dropna(subset=["entry_price", "exit_price", "take_profit", "size_usd",
                       "exit_reason", "asset", "side", "opened_at"]).copy()
print(f"After drop critical: {len(mr)}")

# v1.28 corrected pnl
def corrected_pnl(row):
    correct_shares = round((row["size_usd"] / row["entry_price"]) * DISCOUNT, 2)
    if row["exit_reason"] == "take_profit":
        exit_p = row["take_profit"]
    else:
        exit_p = row["exit_price"]
    return correct_shares * exit_p - row["size_usd"]

mr["pnl_corrected"] = mr.apply(corrected_pnl, axis=1)

# Feature engineering
mr["secs_into_window"] = 900 - mr["secs_remaining_at_entry"]
mr["hour_utc"] = pd.to_datetime(mr["opened_at"], unit="s", utc=True).dt.hour
mr["cheap_side_strength"] = 0.5 - mr["entry_price"]
# Fill NaNs in optional features with 0 (matches "missing" semantics in older trades)
for c in ["spread_at_entry", "price_60s_before_entry", "price_30s_before_entry",
          "price_velocity", "cross_window_pct", "btc_pct_change_at_entry",
          "up_price_at_window_start", "liquidity", "secs_remaining_at_entry"]:
    if c in mr.columns:
        mr[c] = mr[c].fillna(0)

# One-hots
for a in ["BTC", "ETH", "SOL"]:
    mr[f"asset_{a}"] = (mr["asset"] == a).astype(int)
mr["side_UP"] = (mr["side"] == "UP").astype(int)

FEATURES = [
    "entry_price", "secs_remaining_at_entry", "btc_pct_change_at_entry",
    "up_price_at_window_start", "liquidity", "spread_at_entry",
    "price_60s_before_entry", "price_30s_before_entry", "price_velocity",
    "cross_window_pct", "secs_into_window", "hour_utc", "cheap_side_strength",
    "asset_BTC", "asset_ETH", "asset_SOL", "side_UP",
]

# Sort chronologically for time-series CV
mr = mr.sort_values("opened_at").reset_index(drop=True)
mr = mr.dropna(subset=FEATURES).copy()

X = mr[FEATURES].values
y = (mr["pnl_corrected"] > 0).astype(int).values
pnl = mr["pnl_corrected"].values

print(f"\nFinal n={len(mr)}, positive rate={y.mean():.3f}, "
      f"mean pnl_corrected=${pnl.mean():+.4f}, std=${pnl.std():.4f}")

# Baseline
print("\n=== Baseline (all trades) ===")
print(f"  n={len(mr)}  WR={y.mean()*100:.2f}%  mean_pnl=${pnl.mean():+.4f}  "
      f"sharpe-like={pnl.mean()/pnl.std():.4f}")

# ----- 5-fold time series CV -----
tscv = TimeSeriesSplit(n_splits=5)
fold_rows = []
threshold_rows = []
all_preds = np.zeros(len(mr)) - 1.0  # store oof probs

for fi, (tr, te) in enumerate(tscv.split(X)):
    Xtr, Xte = X[tr], X[te]
    ytr, yte = y[tr], y[te]
    pnlte = pnl[te]

    clf = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=20,
        random_state=42,
    )
    clf.fit(Xtr, ytr)
    proba = clf.predict_proba(Xte)[:, 1]
    pred = (proba > 0.5).astype(int)
    all_preds[te] = proba

    auc = roc_auc_score(yte, proba) if len(set(yte)) > 1 else float("nan")
    acc = accuracy_score(yte, pred)
    prec = precision_score(yte, pred, zero_division=0)
    rec = recall_score(yte, pred, zero_division=0)
    base_ev = pnlte.mean()
    base_wr = yte.mean()
    print(f"\nFold {fi+1}: n_tr={len(tr)} n_te={len(te)}  acc={acc:.3f}  AUC={auc:.3f}  "
          f"prec={prec:.3f}  rec={rec:.3f}  base_ev=${base_ev:+.3f}  base_wr={base_wr:.3f}")
    fold_rows.append({
        "fold": fi+1, "n_train": len(tr), "n_test": len(te),
        "accuracy": acc, "auc": auc, "precision": prec, "recall": rec,
        "baseline_ev": base_ev, "baseline_wr": base_wr,
    })

    for thr in [0.5, 0.55, 0.6, 0.65, 0.7]:
        mask_p = proba > thr
        n_kept = int(mask_p.sum())
        if n_kept == 0:
            threshold_rows.append({
                "fold": fi+1, "threshold": thr, "n_kept": 0,
                "wr": float("nan"), "mean_pnl": float("nan"),
                "vs_baseline_delta": float("nan"),
            })
            continue
        kept_pnl = pnlte[mask_p]
        kept_wr = (yte[mask_p]).mean()
        threshold_rows.append({
            "fold": fi+1, "threshold": thr, "n_kept": n_kept,
            "wr": kept_wr, "mean_pnl": kept_pnl.mean(),
            "vs_baseline_delta": kept_pnl.mean() - base_ev,
        })

folds_df = pd.DataFrame(fold_rows)
thr_df = pd.DataFrame(threshold_rows)
print("\n=== Fold summary ===")
print(folds_df.to_string(index=False))
print("\n=== Threshold sweep (per fold) ===")
print(thr_df.to_string(index=False))

# Aggregated threshold view (across all folds)
agg = thr_df.dropna().groupby("threshold").agg(
    total_kept=("n_kept", "sum"),
    mean_wr=("wr", "mean"),
    mean_pnl=("mean_pnl", "mean"),
    mean_delta=("vs_baseline_delta", "mean"),
).reset_index()
print("\n=== Threshold aggregate (mean across folds) ===")
print(agg.to_string(index=False))

# OOF combined view (only on folded test rows; first chunk has no preds)
oof_mask = all_preds >= 0
oof_pnl = pnl[oof_mask]
oof_proba = all_preds[oof_mask]
oof_y = y[oof_mask]
print(f"\n=== OOF combined (n={oof_mask.sum()}) ===")
print(f"  baseline EV ${oof_pnl.mean():+.4f}  WR {oof_y.mean():.3f}")
combined_thr_rows = []
for thr in [0.5, 0.55, 0.6, 0.65, 0.7]:
    m = oof_proba > thr
    n_kept = int(m.sum())
    if n_kept == 0:
        combined_thr_rows.append({"threshold": thr, "n_kept": 0,
                                  "wr": float("nan"), "mean_pnl": float("nan"),
                                  "vs_baseline_delta": float("nan")})
        continue
    combined_thr_rows.append({
        "threshold": thr, "n_kept": n_kept,
        "wr": oof_y[m].mean(), "mean_pnl": oof_pnl[m].mean(),
        "vs_baseline_delta": oof_pnl[m].mean() - oof_pnl.mean(),
    })
combined_thr_df = pd.DataFrame(combined_thr_rows)
print(combined_thr_df.to_string(index=False))

# Refit full and feature importance via permutation
print("\n=== Full-data refit + permutation importance ===")
final = HistGradientBoostingClassifier(
    max_iter=200, learning_rate=0.05, max_depth=4, min_samples_leaf=20, random_state=42,
)
final.fit(X, y)
pi = permutation_importance(final, X, y, n_repeats=10, random_state=42, scoring="roc_auc")
imp_df = pd.DataFrame({
    "feature": FEATURES,
    "importance_mean": pi.importances_mean,
    "importance_std": pi.importances_std,
}).sort_values("importance_mean", ascending=False)
print(imp_df.to_string(index=False))

# Asset/side/hour breakouts of predicted-positive at thr=0.55
PRED_THR = 0.55
oof_kept_idx = np.where(oof_mask)[0][oof_proba > PRED_THR]
mr_oof = mr.iloc[np.where(oof_mask)[0]].copy()
mr_oof["proba"] = oof_proba
mr_oof["kept"] = mr_oof["proba"] > PRED_THR

print(f"\n=== Predicted-positive (thr={PRED_THR}) breakouts ===")
print("By asset:")
for a, sub in mr_oof[mr_oof["kept"]].groupby("asset"):
    print(f"  {a}: n={len(sub)} WR={(sub['pnl_corrected']>0).mean():.3f} EV=${sub['pnl_corrected'].mean():+.3f}")
print("By side:")
for s, sub in mr_oof[mr_oof["kept"]].groupby("side"):
    print(f"  {s}: n={len(sub)} WR={(sub['pnl_corrected']>0).mean():.3f} EV=${sub['pnl_corrected'].mean():+.3f}")
print("By hour bucket (0-5,6-11,12-17,18-23):")
for lo, hi in [(0,5),(6,11),(12,17),(18,23)]:
    sub = mr_oof[(mr_oof["kept"]) & (mr_oof["hour_utc"].between(lo, hi))]
    if len(sub):
        print(f"  {lo:02d}-{hi:02d}: n={len(sub)} WR={(sub['pnl_corrected']>0).mean():.3f} EV=${sub['pnl_corrected'].mean():+.3f}")

# Save outputs
imp_df.to_csv(ROOT / "ml_feature_importance.csv", index=False)
agg_out = agg.copy()
agg_out.to_csv(ROOT / "ml_threshold_ev_tradeoff.csv", index=False)
thr_df.to_csv(ROOT / "ml_threshold_per_fold.csv", index=False)
folds_df.to_csv(ROOT / "ml_fold_summary.csv", index=False)
combined_thr_df.to_csv(ROOT / "ml_oof_threshold.csv", index=False)

# Save all-features-correlation against pnl_corrected for diagnostic
corr_rows = []
for f in FEATURES:
    try:
        c = np.corrcoef(mr[f].values, mr["pnl_corrected"].values)[0,1]
        corr_rows.append({"feature": f, "corr_with_pnl": c})
    except Exception:
        pass
corr_df = pd.DataFrame(corr_rows).sort_values("corr_with_pnl", key=lambda s: s.abs(), ascending=False)
print("\n=== Feature corr with pnl_corrected (Pearson) ===")
print(corr_df.to_string(index=False))
corr_df.to_csv(ROOT / "ml_feature_correlations.csv", index=False)

print("\nDone.")
