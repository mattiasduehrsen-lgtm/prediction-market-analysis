"""
Signal engine for 5-minute Up/Down markets.

Strategy: Early-window mean reversion — enter cheap side, hold to 50¢.

Entry (first 45 seconds only — limit buy between 30-39¢):
  - Place a limit buy on whichever side (UP or DOWN) is between 30¢ and 39¢
  - Only within first 45s of the window (≥255s must remain) — after that, skip and wait for next window
  - BTC flatness filter: skip if Chainlink pct_change is outside ±0.02% (BTC already moving)
  - BTC momentum filter: skip if BTC is moving against your side faster than BTC_SKIP_RATE $/min
  - Minimum liquidity required

Exit rules (hard exits only — no trailing stops):
  1. Price hits TAKE_PROFIT (92¢)  → exit, full reversal captured
  2. Hard floor: price drops below 8¢ → exit, mean reversion failed
  3. FORCE_EXIT seconds left       → close at near-settlement price (5s out ≈ $0 or $1)

Key lessons (from 158-trade analysis):
  - All trailing stops (z1, z2, z3) had 0% win rate — they cut mid-reversion before reaching 50¢
  - ENTRY_MIN raised 0.15→0.30: entries <25¢ had 2.9% WR (-$185 total); 30-40¢ = 55-67% WR
  - Entry window tightened 90s→45s: <150s remaining = 0% WR; 200-250s remaining = 60% WR
  - When held to TP: 100% win rate. Let positions breathe.
"""
from __future__ import annotations

from src.bot.market_5m import (
    Market5m,
    ENTRY_MIN, ENTRY_MAX, TAKE_PROFIT,
    MIN_SECONDS, FORCE_EXIT, SOFT_EXIT_SECS, SOFT_EXIT_PRICE, BTC_SKIP_RATE, BTC_MAGNITUDE_MAX,
)


def should_enter(
    market: Market5m,
    btc_rate_per_min: float = 0.0,
    cl_pct_change: float = 0.0,
) -> tuple[bool, str, float]:
    """
    Returns (should_enter, side, entry_price).
    side is "UP" or "DOWN" — always the cheaper side.
    btc_rate_per_min: BTC $/min change since window start (+ve = rising, -ve = falling).
    cl_pct_change: Chainlink % change since window start — must be flat (±0.02%) to enter.
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

    # BTC magnitude filter: skip if Chainlink shows BTC has already moved more than
    # BTC_MAGNITUDE_MAX from window start. A move that large is a real trend, not
    # a temporary dislocation — the cheap side is priced correctly and won't revert.
    # 0.15% replaces the old ±0.02% flatness filter which was too aggressive.
    if cl_pct_change != 0.0 and abs(cl_pct_change) > BTC_MAGNITUDE_MAX:
        print(f"[SIGNAL] Skip — BTC move too large: {cl_pct_change:+.3f}% (max ±{BTC_MAGNITUDE_MAX}%)")
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

    # Priority 1: take profit at 50¢ — mean reversion complete, exit immediately
    if current >= take_profit:
        return True, "take_profit"

    # Priority 2: hard floor stop — if our side drops below 8¢, the market has
    # essentially fully resolved against us. Mean reversion from 0.08 → 0.50 requires
    # a 6× probability shift in remaining seconds — observed rate: ~0%.
    # This is NOT a trailing stop (which fires mid-reversion); it's an extreme floor that
    # only triggers when the token is already near-worthless. Saves ~$4/trade vs riding to 0.005.
    if current <= 0.08:
        return True, "hard_stop_floor"

    # Trailing stops removed: z1 net -$383, z2 net -$26, z3 net $0 but same pattern.
    # All had 0% win rate — they cut positions mid-reversion before reaching 50¢ TP.
    # Let positions ride to TP (50¢) or force_exit_time. Data: 100% WR at TP vs 0% at stops.

    # Priority 3: soft exit — stalled reversion with ~2min left
    # If still deeply below 25¢ at 115s remaining, recovery to 0.92 is near-impossible.
    # Exit gracefully rather than ride to the hard floor (saves ~$8-12 vs waiting).
    if seconds_remaining <= SOFT_EXIT_SECS and current <= SOFT_EXIT_PRICE:
        return True, "soft_exit_stalled"

    # Priority 4: time-based force exit
    if seconds_remaining <= FORCE_EXIT:
        return True, "force_exit_time"

    return False, ""


def take_profit_price(entry_price: float) -> float:
    return TAKE_PROFIT
