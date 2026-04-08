"""
Signal engine for 5m/15m Up/Down markets.

Two strategies:
  mean_reversion — buy cheap side (28-39¢), bet on reversal within window
  momentum       — enter at window open, bet same direction as previous window (PolyBackTest edge)
"""
from __future__ import annotations

from src.bot.market_5m import (
    Market5m,
    ENTRY_MIN, ENTRY_MAX, TAKE_PROFIT,
    MIN_SECONDS, FORCE_EXIT, SOFT_EXIT_SECS, SOFT_EXIT_PRICE,
    BTC_SKIP_RATE, BTC_MAGNITUDE_MAX,
    MOMENTUM_ENTRY_WINDOW, MOMENTUM_MIN_PREV_MOVE,
)


def should_enter(
    market: Market5m,
    btc_rate_per_min: float = 0.0,
    cl_pct_change: float = 0.0,
    min_seconds: float = MIN_SECONDS,
) -> tuple[bool, str, float]:
    """
    Mean-reversion entry: buy the cheap side (ENTRY_MIN–ENTRY_MAX) in the entry window.
    Returns (should_enter, side, entry_price).
    min_seconds: seconds that must remain to allow entry (computed from window size in caller).
    """
    secs = market.seconds_remaining

    if secs < min_seconds:
        return False, "", 0.0

    if market.liquidity < 1000:
        return False, "", 0.0

    # Cheaper side is our mean-reversion candidate
    if market.up_price <= market.down_price:
        side, price = "UP", market.up_price
    else:
        side, price = "DOWN", market.down_price

    if price < ENTRY_MIN or price > ENTRY_MAX:
        return False, "", 0.0

    # BTC magnitude filter: skip if Chainlink shows a real trend already established
    if cl_pct_change != 0.0 and abs(cl_pct_change) > BTC_MAGNITUDE_MAX:
        print(f"[SIGNAL] Skip — {market.asset} move too large: {cl_pct_change:+.3f}% (max ±{BTC_MAGNITUDE_MAX}%)")
        return False, "", 0.0

    # BTC momentum filter: skip if asset is moving hard against our side
    if side == "UP" and btc_rate_per_min < -BTC_SKIP_RATE:
        print(f"[SIGNAL] Skip UP — {market.asset} falling ${btc_rate_per_min:.1f}/min (threshold -${BTC_SKIP_RATE}/min)")
        return False, "", 0.0
    if side == "DOWN" and btc_rate_per_min > BTC_SKIP_RATE:
        print(f"[SIGNAL] Skip DOWN — {market.asset} rising ${btc_rate_per_min:.1f}/min (threshold +${BTC_SKIP_RATE}/min)")
        return False, "", 0.0

    return True, side, price


def should_enter_momentum(
    market: Market5m,
    cross_window_pct: float,
    min_prev_move: float = MOMENTUM_MIN_PREV_MOVE,
) -> tuple[bool, str, float]:
    """
    Momentum entry: enter at window open, bet same direction as previous window.
    Returns (should_enter, side, entry_price).

    cross_window_pct: Chainlink % move from prev window start to current window start.
      Positive = prev window BTC went UP → bet UP continues.
      Negative = prev window BTC went DOWN → bet DOWN continues.

    Only enters within MOMENTUM_ENTRY_WINDOW seconds of window open.
    """
    secs = market.seconds_remaining
    ws   = market.window_seconds

    # Must be in the first MOMENTUM_ENTRY_WINDOW seconds of the window
    if secs < ws - MOMENTUM_ENTRY_WINDOW:
        return False, "", 0.0

    if market.liquidity < 1000:
        return False, "", 0.0

    # Need meaningful previous move — avoid entering on flat/stale windows
    if abs(cross_window_pct) < min_prev_move:
        return False, "", 0.0

    # No prev window data yet (first window after bot restart)
    if cross_window_pct == 0.0:
        return False, "", 0.0

    if cross_window_pct > 0:
        side  = "UP"
        price = market.up_price
    else:
        side  = "DOWN"
        price = market.down_price

    return True, side, price


def should_exit(
    side: str,
    entry_price: float,
    current_up_price: float,
    take_profit: float,
    seconds_remaining: float,
    soft_exit_secs: float = SOFT_EXIT_SECS,
    hard_stop_max_remaining: float = float("inf"),
) -> tuple[bool, str]:
    """
    Returns (should_exit, reason).
    soft_exit_secs: scaled to window size by caller (SOFT_EXIT_SECS for 5m, ~300 for 15m).
    hard_stop_max_remaining: hard floor only fires when seconds_remaining < this value.
      Default inf = fires any time (5m behaviour).
      Pass 240 for 15m = only fires in last 4 minutes when recovery is unlikely.
    """
    current = current_up_price if side == "UP" else (1.0 - current_up_price)

    if current >= take_profit:
        return True, "take_profit"

    # Hard floor: token near-worthless, mean reversion failed.
    # Time-gated so 15m positions aren't killed early when recovery is still possible.
    if current <= 0.08 and seconds_remaining < hard_stop_max_remaining:
        return True, "hard_stop_floor"

    # Soft exit: stalled reversion with time running out
    if seconds_remaining <= soft_exit_secs and current <= SOFT_EXIT_PRICE:
        return True, "soft_exit_stalled"

    if seconds_remaining <= FORCE_EXIT:
        return True, "force_exit_time"

    return False, ""


def take_profit_price(entry_price: float) -> float:
    return TAKE_PROFIT
