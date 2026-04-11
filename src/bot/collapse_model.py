"""
GBM collapse probability scorer.

Predicts probability that a mean-reversion entry will hit hard_stop_floor
(contract collapses to near-zero) instead of take_profit.

Model: GradientBoostingClassifier trained on 685 paper trades (Cowork, 2026-04-11)
  AUC 0.714 (5-fold CV), threshold=0.30
  Classes: 0=take_profit, 1=hard_stop_floor
  At threshold=0.30: blocks 60.5% of HSF, retains 62.1% of TP entries

Features (must be passed in this order):
  entry_price, dist_to_tp, rel_entry_price,
  btc_pct_change_at_entry, secs_remaining_at_entry, time_pressure,
  liquidity, log_liquidity,
  price_60s_before_entry, price_30s_before_entry,
  price_velocity, entry_momentum,
  side_numeric, entry_vs_window_start
"""
from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Optional

_MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "collapse_gbm.joblib"

# Lazy-loaded singleton — only imports joblib/sklearn when first called
_pipeline = None


def _load() -> object:
    global _pipeline
    if _pipeline is None:
        import joblib
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # suppress sklearn version mismatch
            _pipeline = joblib.load(_MODEL_PATH)
    return _pipeline


# Threshold recommended by Cowork: blocks 60.5% HSF, retains 62.1% TP
COLLAPSE_THRESHOLD = 0.30


def collapse_prob(
    entry_price: float,
    take_profit: float,
    btc_pct_change_at_entry: float,
    secs_remaining: float,
    liquidity: float,
    price_60s: float,
    price_30s: float,
    price_velocity: float,
    side: str,
    up_price_at_window_start: float,
) -> float:
    """
    Returns probability [0,1] that this entry will collapse (hard_stop_floor).
    Returns 0.0 if the model can't be loaded or required inputs are missing.
    """
    try:
        pipe = _load()
    except Exception:
        return 0.0

    dist_to_tp          = take_profit - entry_price
    rel_entry_price     = entry_price / take_profit if take_profit > 0 else 0.0
    time_pressure       = 1.0 / (secs_remaining + 1.0)
    log_liquidity       = math.log1p(liquidity)
    entry_momentum      = (price_30s - price_60s) if (price_30s > 0 and price_60s > 0) else 0.0
    side_numeric        = 1.0 if side == "UP" else 0.0
    entry_vs_ws         = entry_price - up_price_at_window_start

    X = [[
        entry_price, dist_to_tp, rel_entry_price,
        btc_pct_change_at_entry, secs_remaining, time_pressure,
        liquidity, log_liquidity,
        price_60s, price_30s,
        price_velocity, entry_momentum,
        side_numeric, entry_vs_ws,
    ]]

    try:
        prob = float(pipe.predict_proba(X)[0][1])   # class 1 = hard_stop_floor
    except Exception:
        return 0.0

    return prob


def should_skip(prob: float) -> bool:
    return prob >= COLLAPSE_THRESHOLD
