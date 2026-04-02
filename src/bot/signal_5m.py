"""
Signal engine for 5-minute Up/Down markets.

Strategy: Mean reversion at extremes
  - UP price ≤ 0.05  → buy UP  (bet it bounces back above 0.20)
  - DOWN price ≤ 0.05 → buy DOWN (bet it bounces back above 0.20)

The thesis: when the market prices one side at 1-5¢, BTC has moved sharply
in one direction in the last few minutes. These extreme moves often partially
revert within the remaining window, pushing the cheap side back to 15-25¢.

Only enter if ≥ MIN_SECONDS_TO_ENTER seconds remain (default 90s).
Force-close any open position when ≤ FORCE_EXIT_SECONDS remain (default 60s).
"""
from __future__ import annotations

from src.bot.market_5m import Market5m, ENTRY_MAX, TAKE_PROFIT, STOP_LOSS, MIN_SECONDS, FORCE_EXIT


def should_enter(market: Market5m) -> tuple[bool, str, float]:
    """
    Check if we should enter a position.
    Returns (should_enter, side, entry_price).
    side is "UP" or "DOWN".
    """
    secs = market.seconds_remaining

    if secs < MIN_SECONDS:
        return False, "", 0.0

    if market.liquidity < 1000:
        return False, "", 0.0

    # Buy UP when UP is near zero (BTC tanked, market thinks it won't recover)
    if market.up_price <= ENTRY_MAX:
        return True, "UP", market.up_price

    # Buy DOWN when DOWN is near zero (BTC surged, market thinks it won't reverse)
    if market.down_price <= ENTRY_MAX:
        return True, "DOWN", market.down_price

    return False, "", 0.0


def should_exit(
    side: str,
    entry_price: float,
    current_up_price: float,
    take_profit: float,
    stop_loss: float,
    seconds_remaining: float,
) -> tuple[bool, str]:
    """
    Check if an open position should be exited.
    Returns (should_exit, reason).
    """
    # Force-exit when close to window end
    if seconds_remaining <= FORCE_EXIT:
        return True, "force_exit"

    if side == "UP":
        current = current_up_price
    else:
        current = 1.0 - current_up_price  # DOWN price

    if current >= take_profit:
        return True, "take_profit"

    if current <= stop_loss:
        return True, "stop_loss"

    return False, ""


def take_profit_price(entry_price: float) -> float:
    """Target exit price — revert from entry toward TAKE_PROFIT."""
    return TAKE_PROFIT


def stop_loss_price(entry_price: float) -> float:
    """Stop loss price — below this we cut the position."""
    return STOP_LOSS
