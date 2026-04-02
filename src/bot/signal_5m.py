"""
Signal engine for 5-minute Up/Down markets.

Strategy: Mean reversion at extremes — learned from v61 of a successful bot.

Entry:
  - UP price  ≤ ENTRY_MAX (0.05) → buy UP
  - DOWN price ≤ ENTRY_MAX (0.05) → buy DOWN
  - Only if ≥ MIN_SECONDS remain in the window

Exit rules (in priority order):
  1. Price hits FORCE_EXIT_PRICE (0.85) → unconditional take — never give back a big win
  2. Price hits TAKE_PROFIT (0.30)      → normal take profit
  3. Time hits FORCE_EXIT seconds left  → close regardless of price
  4. NO stop loss — binary markets need room; stop losses cut on noise right before reversals

Key lessons from the v61 bot:
  - Stop losses lose more than they save in binary markets
  - Martingale is a death spiral — we don't do it
  - 85¢ unconditional force-exit captures big wins before they evaporate
"""
from __future__ import annotations

from src.bot.market_5m import (
    Market5m,
    ENTRY_MAX, TAKE_PROFIT, FORCE_EXIT_PRICE, MIN_SECONDS, FORCE_EXIT,
)


def should_enter(market: Market5m) -> tuple[bool, str, float]:
    """
    Returns (should_enter, side, entry_price).
    side is "UP" or "DOWN".
    """
    secs = market.seconds_remaining

    if secs < MIN_SECONDS:
        return False, "", 0.0

    if market.liquidity < 1000:
        return False, "", 0.0

    if market.up_price <= ENTRY_MAX:
        return True, "UP", market.up_price

    if market.down_price <= ENTRY_MAX:
        return True, "DOWN", market.down_price

    return False, "", 0.0


def should_exit(
    side: str,
    entry_price: float,
    current_up_price: float,
    take_profit: float,
    seconds_remaining: float,
) -> tuple[bool, str]:
    """
    Returns (should_exit, reason).
    No stop loss — let positions breathe.
    """
    current = current_up_price if side == "UP" else (1.0 - current_up_price)

    # Priority 1: unconditional exit at 85¢ — never give back a near-certain win
    if current >= FORCE_EXIT_PRICE:
        return True, "force_exit_price"

    # Priority 2: normal take profit
    if current >= take_profit:
        return True, "take_profit"

    # Priority 3: time-based force exit
    if seconds_remaining <= FORCE_EXIT:
        return True, "force_exit_time"

    return False, ""


def take_profit_price(entry_price: float) -> float:
    return TAKE_PROFIT
