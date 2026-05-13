# ML Feature Exploration - 2026-05-10

## Headline finding

**No signal.** A gradient-boosted classifier trained on every entry-time feature
in `trades.csv` (microstructure, BTC context, timing, asset/side dummies) cannot
identify a +EV subset of MR-15m PAPER trades after v1.28 corrections. Across 5
chronological CV folds, mean AUC is **0.50** (folds: 0.54, 0.48, 0.41, 0.53,
0.52 — straddling chance, with one fold meaningfully *worse* than chance).
Critically, **every probability threshold from 0.50 to 0.70 produces a
predicted-positive subset whose mean PnL is *worse* than the baseline of "take
all trades."** At threshold 0.55, OOF predicted-positive EV is **-$1.99/trade**
vs baseline -$0.95/trade — the model selects more, not less, of the structural
loss. This is consistent with the strategy being structurally noise rather than
a poorly-filtered edge.

## Method

- Data: `cowork_snapshot/5m_trading/trades_v1_29_postdeploy.csv`, 1686 rows,
  filtered to `strategy=mean_reversion` & `window=15m` → 721 trades.
- Target: `pnl_corrected = round((size_usd / entry_price) * 0.955, 2) * exit_p
  - size_usd`, where `exit_p = take_profit` for TP exits else `exit_price`.
  Binary classification target: `pnl_corrected > 0`.
- Features (entry-time only, no leakage): `entry_price`,
  `secs_remaining_at_entry`, `btc_pct_change_at_entry`,
  `up_price_at_window_start`, `liquidity`, `spread_at_entry`,
  `price_60s_before_entry`, `price_30s_before_entry`, `price_velocity`,
  `cross_window_pct`, derived `secs_into_window`, `hour_utc`,
  `cheap_side_strength`, and one-hots for asset (BTC/ETH/SOL) and side (UP).
- Model: `sklearn.HistGradientBoostingClassifier(max_iter=200, lr=0.05,
  max_depth=4, min_samples_leaf=20)`.
- CV: `TimeSeriesSplit(n_splits=5)`, sorted by `opened_at` — strict past →
  future, no shuffling.

## Baseline (all trades)

| metric | value |
|---|---|
| n | 721 |
| WR (`pnl_corrected > 0`) | **47.71%** |
| mean `pnl_corrected` | **-$0.998** |
| std | $10.71 |
| sharpe-like (mean/std) | -0.093 |

## Cross-validated performance

| fold | n_train | n_test | accuracy | AUC | precision | recall | baseline_ev | baseline_wr |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 121 | 120 | 0.492 | 0.541 | 0.485 | 0.267 | -$0.29 | 0.500 |
| 2 | 241 | 120 | 0.542 | 0.483 | 0.625 | 0.667 | +$0.65 | 0.625 |
| 3 | 361 | 120 | 0.442 | 0.409 | 0.438 | 0.764 | -$2.75 | 0.458 |
| 4 | 481 | 120 | 0.483 | 0.527 | 0.437 | 0.585 | -$2.15 | 0.442 |
| 5 | 601 | 120 | 0.500 | 0.521 | 0.577 | 0.441 | -$0.21 | 0.567 |
| **mean** | | | **0.492** | **0.496** | **0.512** | **0.545** | **-$0.95** | **0.519** |

Mean AUC of **0.496** is statistically indistinguishable from chance (0.50).
The wide swing in baseline EV across folds (+$0.65 to -$2.75) confirms regime
non-stationarity — fold 3 spans the worst stretch and the model fits it least
well of all (AUC 0.41).

## Predicted-positive EV vs baseline

OOF combined (folds 1-5 stacked, n=600, baseline EV -$0.948, WR 0.518):

| threshold | n_kept | WR | mean_pnl | vs baseline |
|---:|---:|---:|---:|---:|
| 0.50 | 332 | 0.509 | -$1.619 | **-$0.671** |
| 0.55 | 292 | 0.493 | -$1.990 | **-$1.042** |
| 0.60 | 251 | 0.494 | -$2.062 | **-$1.114** |
| 0.65 | 204 | 0.480 | -$2.321 | **-$1.373** |
| 0.70 | 156 | 0.474 | -$2.508 | **-$1.560** |

Higher confidence → *worse* outcomes. The model's "most confident wins" lose
faster than random. This is the signature of overfit-to-training noise: the
features the model upweights (cross_window_pct, liquidity, hour_utc) drift
across regimes and don't generalize forward.

No threshold clears the structural -$1.99/win haircut needed for breakeven.

## Feature importance (top 10, permutation on full refit, scoring=AUC)

| feature | importance | std |
|---|---:|---:|
| cross_window_pct | 0.117 | 0.010 |
| liquidity | 0.073 | 0.007 |
| entry_price | 0.069 | 0.006 |
| btc_pct_change_at_entry | 0.067 | 0.009 |
| hour_utc | 0.060 | 0.005 |
| up_price_at_window_start | 0.042 | 0.003 |
| secs_remaining_at_entry | 0.033 | 0.003 |
| price_30s_before_entry | 0.032 | 0.004 |
| secs_into_window | 0.017 | 0.003 |
| asset_SOL | 0.011 | 0.001 |

Caveat: these are full-data importances and reflect what the model *uses*, not
what generalizes — note that the same features fail to deliver OOS. Pearson
correlations of features with `pnl_corrected` are all `|r| < 0.08`, consistent
with no exploitable linear or low-order signal.

## Asset / side / time-of-day breakouts (predicted-positive at thr=0.55)

By asset:
- BTC: n=152, WR 0.447, EV -$2.80
- ETH: n=122, WR 0.541, EV -$1.18
- SOL: n=18, WR 0.556, EV -$0.64

By side:
- UP: n=173, WR 0.514, EV -$1.46
- DOWN: n=119, WR 0.462, EV -$2.76

By hour-bucket UTC (predicted-positive only):
- 00-05: n=92, WR 0.500, EV -$1.94
- 06-11: n=93, WR 0.516, EV -$1.62
- 12-17: n=52, WR 0.519, EV -$1.32
- 18-23: n=55, WR 0.418, EV -$3.33

No segment of the predicted-positive subset is +EV. SOL has the smallest loss
(consistent with the n=74 SOL UP +$0.53 EV finding from the v1.28 retro
analysis), but the model only flags 18 SOL trades — too few to act on.

The 18-23 UTC hour bucket is notably the worst, suggesting a possible
"avoid-this-window" rule, but this is in-sample and the magnitude could easily
be noise on n=55.

## Verdict and next steps

**Verdict: (c) escalate to option 1 / (d) accept option 5.** The 17 entry-time
features carry essentially no predictive signal about MR-15m outcomes after
v1.28 honest accounting. The classifier doesn't rediscover the existing filters
— it finds nothing to discover. Mean AUC 0.496 with confidence-monotonically-worse
EV is the textbook footprint of a structurally edgeless strategy plus
post-hoc-inflated training labels.

Concrete recommendations:

1. **Do not deploy an ML filter as v1.31.** Predicted-positive EV is worse
   than baseline at every threshold; turning it on would accelerate losses.
2. **Do not bother translating top features into rules.** `cross_window_pct`,
   `liquidity`, and `hour_utc` rank highest in permutation importance but
   correlate with `pnl_corrected` at |r| < 0.06 and contribute negative OOS
   delta. Any rule built from them is curve-fit.
3. **Escalate to option 1 (longer-horizon markets) or accept option 5 (archive
   MR-15m).** The strategy's structural haircut (TP=0.60 net of fees and the
   0.955 share discount = ~-$1.99 per loss vs ~+$2.50 per win, requiring ~44%
   WR just to breakeven on a 1:1 win/loss ratio that this strategy doesn't
   achieve) is not closeable by smarter filtering on these features.
4. **If pursuing one more iteration:** the one segment with marginal hope is
   SOL UP. The 18-23 UTC dead zone is worth a quick rule-based test (skip
   entries 18:00-23:59 UTC) before archiving — but on n=55 OOF predicted, this
   is a suggestive heuristic, not a finding.

## Honest caveats

- **In-sample on 721 trades.** Real OOS is typically 30-50% worse than CV.
  Here CV is already negative, so the verdict is robust to that haircut.
- **The 0.955 share discount is itself an estimate** (true value lives in
  0.95-0.96). A ±0.005 swing changes per-trade EV by ~$0.03 — not enough to
  flip the headline.
- **Known regime breaks** (May 1 crash, filter version bumps) violate IID-ness
  across folds. Fold-to-fold AUC variance (0.41-0.54) is a direct symptom. We
  cannot rule out that some folds *do* contain signal that's drowned by others;
  but that itself is the core problem — no stable, exploitable edge.
- **n=721 is small** for ML. A fold with n=120 has SE on EV of ~$1.00 — fold
  baseline EVs of +$0.65 vs -$2.75 may be partly noise. The aggregate
  conclusion (mean AUC ≈ 0.50, predicted-positive worse than baseline at every
  threshold) is more robust than any single fold.
- **Feature coverage is partial** for older trades (`spread_at_entry`,
  `cross_window_pct` were added later, filled with 0 here). The most-recent
  ~200-trade slice has the richest features but also the worst raw EV, so
  fuller features didn't rescue performance.

Artifacts:
- `ml_feature_importance.csv` — permutation importances on full refit
- `ml_threshold_ev_tradeoff.csv` — per-threshold aggregate (mean across folds)
- `ml_threshold_per_fold.csv` — per-fold threshold sweep
- `ml_oof_threshold.csv` — OOF stacked threshold sweep
- `ml_fold_summary.csv` — per-fold metrics
- `ml_feature_correlations.csv` — Pearson correlations of features with
  `pnl_corrected`
- `analysis_opus_ml.py` — runnable analysis script
