"""
take_profit_optimizer.py
────────────────────────────────────────────────────────────────────
Optimal take-profit targets for Polymarket mean-reversion bot.
Derived from 685 paper-trade back-test (682 BTC up/down 5-min windows).

USAGE:  import tp_optimizer; tp = tp_optimizer.get_take_profit(0.34)
"""

from __future__ import annotations
import warnings


# ──────────────────────────────────────────────────────────────────────────────
# Core formula (fitted from bucket optimisation)
#   TP = 0.80 − 0.53 × entry_price      (entry ≤ 0.42)
#   Full simulation shows: +$2,108 vs −$1,073 actual on 685 trades
# ──────────────────────────────────────────────────────────────────────────────

# Empirical per-bucket optima used to fit the formula:
#   B1 (avg entry 0.307) → TP 0.63   (+105% gain)
#   B2 (avg entry 0.349) → TP 0.64   ( +83% gain)
#   B3 (avg entry 0.370) → TP 0.60   ( +62% gain)
#   B4 (avg entry 0.388) → TP 0.59   ( +52% gain)
#   B5 (avg entry 0.477) → NO EDGE   (skip)

_TP_INTERCEPT = 0.8012   # fitted by OLS on bucket (entry, optimal_tp) pairs
_TP_SLOPE     = -0.5267  # negative: higher entry → lower TP target
_TP_MIN       = 0.55     # never exit this close to entry
_TP_MAX       = 0.75     # never hold for a monster reversion
_ENTRY_MAX    = 0.40     # above this entry price, strategy has negative EV (Cowork: 0.35-0.40 = 47.6% WR, >0.40 = 18.8%)


def get_take_profit(
    entry_price: float,
    mode: str = "piecewise",     # "piecewise" | "linear"
    allow_skip: bool = True,
) -> float | None:
    """
    Return the recommended take-profit price for a given entry price.

    Parameters
    ----------
    entry_price : float
        The price at which the position was entered (e.g. 0.34).
    mode : str
        "piecewise"  – simple step function, easiest to hard-code.
        "linear"     – continuous formula, slightly smoother.
    allow_skip : bool
        If True and entry_price > 0.42, returns None to signal
        "don't take this trade" (strategy has negative EV there).

    Returns
    -------
    float | None
        Take-profit price, or None if the trade should be skipped.
    """
    if allow_skip and entry_price > _ENTRY_MAX:
        return None  # B5 bucket: negative EV, skip

    if mode == "piecewise":
        return _tp_piecewise(entry_price)
    elif mode == "linear":
        return _tp_linear(entry_price)
    else:
        raise ValueError(f"Unknown mode '{mode}'. Choose 'piecewise' or 'linear'.")


def _tp_piecewise(entry_price: float) -> float:
    """
    Step-function TP — easy to audit, works well in practice.

    Entry bucket   →  TP    (required % gain)
    ─────────────────────────────────────────
    ≤ 0.32         →  0.63  (+97 to +127%)
    ≤ 0.36         →  0.62  (+72 to  +82%)
    ≤ 0.40         →  0.60  (+50 to  +67%)
    """
    if   entry_price <= 0.32: return 0.63
    elif entry_price <= 0.36: return 0.62
    else:                     return 0.60   # 0.32–0.40


def _tp_linear(entry_price: float) -> float:
    """
    Continuous linear formula:  TP = 0.8012 − 0.5267 × entry
    Clamped to [0.55, 0.75].
    """
    tp = _TP_INTERCEPT + _TP_SLOPE * entry_price
    return float(max(_TP_MIN, min(_TP_MAX, tp)))


def pct_gain_required(entry_price: float, tp: float) -> float:
    """Return the percentage gain needed from entry to reach tp."""
    return (tp - entry_price) / entry_price * 100.0


# ──────────────────────────────────────────────────────────────────────────────
# Drop-in replacement for your existing TP logic
# ──────────────────────────────────────────────────────────────────────────────

def compute_take_profit(entry_price: float) -> float | None:
    """
    Single entry point for the bot.

    Returns the take-profit price to set when opening a position,
    or None if the trade should not be taken.

    Example
    -------
        tp = compute_take_profit(entry_price=0.34)
        if tp is None:
            log("Skipping trade: entry too high, negative EV")
            return
        place_order(side=side, tp=tp, ...)
    """
    return get_take_profit(entry_price, mode="piecewise", allow_skip=True)


# ──────────────────────────────────────────────────────────────────────────────
# Self-test / lookup table
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Recommended take-profit by entry price\n")
    print(f"{'Entry':>7}  {'TP (pw)':>8}  {'TP (lin)':>9}  {'%Gain(pw)':>10}  {'Action':>8}")
    print("─" * 55)
    for e in [0.20, 0.25, 0.28, 0.30, 0.32, 0.34, 0.36, 0.38, 0.40, 0.42, 0.45, 0.50]:
        tp_pw  = get_take_profit(e, mode="piecewise", allow_skip=False)
        tp_lin = get_take_profit(e, mode="linear",    allow_skip=False)
        action = "SKIP" if e > _ENTRY_MAX else "trade"
        gain   = pct_gain_required(e, tp_pw)
        print(f"  {e:.2f}   {tp_pw:.4f}    {tp_lin:.4f}      {gain:>7.1f}%    {action}")

    print()
    print("Full formula (linear):  TP = 0.8012 − 0.5267 × entry_price")
    print("Piecewise rules:")
    print("  entry ≤ 0.32  →  TP = 0.63")
    print("  entry ≤ 0.36  →  TP = 0.62")
    print("  entry ≤ 0.40  →  TP = 0.60")
    print("  entry  > 0.40 →  SKIP (negative EV)")
