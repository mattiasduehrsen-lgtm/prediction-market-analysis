"""
Signal engine for 5-minute Up/Down markets.

Strategy: Early-window mean reversion with zone-based trailing stop.

Entry (first 90 seconds only — limit buy at 40¢):
  - Place a limit buy at 40¢ on whichever side (UP or DOWN) swings there first
  - Only within first 90s of the window (≥210s must remain) — after that, skip and wait for next window
  - BTC filter: skip if BTC is moving against your side faster than BTC_SKIP_RATE $/min
  - Minimum liquidity required

Exit rules (hard exits — no conditions, no waiting):
  1. Price hits FORCE_EXIT_PRICE (90¢) → hard exit, capture the big win immediately
  2. Price hits TAKE_PROFIT (50¢)     → hard take profit
  3. Zone-based trailing stop         → tighter leash the closer to expiry:
       < 120s left: exit if 5¢ below entry (let it breathe early, not late)
       <  60s left: exit if back at entry or below (no time to recover)
       <  30s left: exit if below 85% of take_profit target
  4. FORCE_EXIT seconds left          → close regardless (avoid settlement chaos)

Key lessons:
  - Entering in the first 2 minutes captures momentum before the market tips irrecoverably
  - Hard exits at targets prevent "90¢ → 0" disasters
  - Zone stops protect capital near expiry without cutting early positions prematurely
"""
from __future__ import annotations

from src.bot.market_5m import (
    Market5m,
    ENTRY_MIN, ENTRY_MAX, TAKE_PROFIT, FORCE_EXIT_PRICE,
    MIN_SECONDS, FORCE_EXIT, BTC_SKIP_RATE,
)


def should_enter(
    market: Market5m,
    btc_rate_per_min: float = 0.0,
) -> tuple[bool, str, float]:
    """
    Returns (should_enter, side, entry_price).
    side is "UP" or "DOWN" — always the cheaper side.
    btc_rate_per_min: BTC $/min change since window start (+ve = rising, -ve = falling).
    """
    secs = market.seconds_remaining

    # Must be in first 2 minutes of the 5-minute window
    if secs < MIN_SECONDS:
        return False, "", 0.0

    # Minimum liquidity
    if market.liquidity < 1000:
        return False, "", 0.0

    # Identify the cheaper side — that's our mean-reversion candidate
    if market.up_price <= market.down_price:
        side, price = "UP", market.up_price
    else:
        side, price = "DOWN", market.down_price

    # Price range: must be between ENTRY_MIN and ENTRY_MAX
    # Below ENTRY_MIN → too extreme, market has already decided, unlikely to recover
    # Above ENTRY_MAX → risk/reward stops making sense (paying too much for the underdog)
    if price < ENTRY_MIN or price > ENTRY_MAX:
        return False, "", 0.0

    # BTC momentum filter: skip if BTC is moving hard against our side
    # UP trade + BTC falling fast → bad entry
    # DOWN trade + BTC rising fast → bad entry
    if side == "UP" and btc_rate_per_min < -BTC_SKIP_RATE:
        print(f"[SIGNAL] Skip UP — BTC falling ${btc_rate_per_min:.1f}/min (threshold -${BTC_SKIP_RATE}/min)")
        return False, "", 0.0
    if side == "DOWN" and btc_rate_per_min > BTC_SKIP_RATE:
        print(f"[SIGNAL] Skip DOWN — BTC rising ${btc_rate_per_min:.1f}/min (threshold +${BTC_SKIP_RATE}/min)")
        return False, "", 0.0

    return True, side, price


def should_exit(
    side: str,
    entry_price: float,
    current_up_price: float,
    take_profit: float,
    seconds_remaining: float,
) -> tuple[bool, str]:
    """
    Returns (should_exit, reason).
    Hard exits — no conditions, no waiting.
    Zone-based trailing stop tightens near expiry.
    """
    current = current_up_price if side == "UP" else (1.0 - current_up_price)

    # Priority 1: hard exit at 90¢ — capture the big win, never let it evaporate
    if current >= FORCE_EXIT_PRICE:
        return True, "force_exit_price"

    # Priority 2: hard take profit at 50¢ — this is the target, exit immediately
    if current >= take_profit:
        return True, "take_profit"

    # Priority 3: zone-based trailing stop — only applies near expiry
    # z1 (< 120s) was removed: price already at 21¢ avg by trigger, locks in
    # losses on trades that still had 120s to recover. Net impact: -$383.
    if seconds_remaining < 30:
        # Very near end: exit if not at least 85% of the way to target
        if current < take_profit * 0.85:   # e.g. < 42.5¢ with <30s left
            return True, "trailing_stop_z3"
    elif seconds_remaining < 60:
        # Near end: exit if we haven't recovered at least back to entry
        if current < entry_price:
            return True, "trailing_stop_z2"

    # Priority 4: time-based force exit
    if seconds_remaining <= FORCE_EXIT:
        return True, "force_exit_time"

    return False, ""


def take_profit_price(entry_price: float) -> float:
    return TAKE_PROFIT
