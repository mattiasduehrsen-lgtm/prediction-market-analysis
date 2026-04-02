"""
Signal engine for BTC strike markets.

Logic:
  1. Find the two markets bracketing current BTC price (one ITM, one OTM)
  2. Assess momentum direction from btc_feed
  3. Generate a trade signal if conditions are met

Signal types:
  - BUY_YES  on OTM strike above: bet BTC will continue rising through next strike
  - BUY_NO   on OTM strike above: bet BTC won't reach the next strike (fading the move)
  - BUY_YES  on ITM strike below: bet BTC will stay above the lower strike
  - BUY_NO   on ITM strike below: bet BTC will fall below the lower strike

Entry conditions (configurable via .env):
  SIGNAL_MIN_MOMENTUM_5M   = 0.3    # min 5-min % move to enter directional trade
  SIGNAL_OTM_YES_MAX       = 0.40   # only buy YES if currently priced below this
  SIGNAL_OTM_YES_MIN       = 0.05   # avoid markets that are already near-certain
  SIGNAL_MIN_LIQUIDITY     = 5000   # minimum $ liquidity in the strike market
  SIGNAL_MIN_HOURS_LEFT    = 1.5    # don't enter within 1.5h of expiry
  SIGNAL_MAX_HOURS_LEFT    = 20     # don't enter if market just opened (too early, wide spreads)
  SIGNAL_TAKE_PROFIT       = 0.15   # exit when YES moves 15 pp in our favor
  SIGNAL_STOP_LOSS         = 0.08   # exit when YES moves 8 pp against us
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

from src.bot.btc_markets import BTCMarketSnapshot, StrikeMarket
from src.bot.btc_feed import BTCState


def _env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


@dataclass
class TradeSignal:
    condition_id: str
    question: str
    strike: int
    side: str           # "YES" or "NO"
    entry_price: float  # price to pay per share
    take_profit: float  # target exit price
    stop_loss: float    # stop exit price
    reason: str
    btc_price: float
    btc_momentum_5m: float
    generated_at: float = 0.0

    def __post_init__(self):
        if self.generated_at == 0.0:
            self.generated_at = time.time()


def generate(snapshot: BTCMarketSnapshot, btc: BTCState) -> list[TradeSignal]:
    """
    Evaluate all strike markets and return any trade signals.
    Returns empty list if no signal conditions are met.
    """
    if btc.price <= 0 or btc.is_stale():
        return []

    min_mom    = _env("SIGNAL_MIN_MOMENTUM_5M", 0.3)
    otm_max    = _env("SIGNAL_OTM_YES_MAX", 0.40)
    otm_min    = _env("SIGNAL_OTM_YES_MIN", 0.05)
    min_liq    = _env("SIGNAL_MIN_LIQUIDITY", 5000)
    min_hours  = _env("SIGNAL_MIN_HOURS_LEFT", 1.5)
    max_hours  = _env("SIGNAL_MAX_HOURS_LEFT", 20)
    tp_delta   = _env("SIGNAL_TAKE_PROFIT", 0.15)
    sl_delta   = _env("SIGNAL_STOP_LOSS", 0.08)

    signals: list[TradeSignal] = []
    btc_price  = btc.price
    momentum   = btc.momentum_5m

    tradeable = [
        m for m in snapshot.markets
        if m.liquidity >= min_liq
        and min_hours <= m.hours_to_expiry <= max_hours
    ]
    if not tradeable:
        return []

    # Sort by strike to find bracketing markets
    tradeable.sort(key=lambda m: m.strike)

    # Split into ITM (strike < btc_price, YES is near 1) and OTM (strike > btc_price, YES is near 0)
    itm = [m for m in tradeable if m.strike < btc_price]
    otm = [m for m in tradeable if m.strike >= btc_price]

    # Closest OTM market (strike just above current price)
    closest_otm = otm[0] if otm else None
    # Closest ITM market (strike just below current price)
    closest_itm = itm[-1] if itm else None

    # --- Signal A: BTC trending UP → buy YES on closest OTM ---
    # The OTM YES is cheap (e.g. 0.20) because BTC hasn't crossed yet.
    # If BTC momentum continues, the YES will appreciate toward 0.5-0.9.
    if closest_otm and momentum >= min_mom:
        yes = closest_otm.yes_price
        if otm_min <= yes <= otm_max:
            signals.append(TradeSignal(
                condition_id=closest_otm.condition_id,
                question=closest_otm.question,
                strike=closest_otm.strike,
                side="YES",
                entry_price=yes,
                take_profit=min(yes + tp_delta, 0.95),
                stop_loss=max(yes - sl_delta, 0.01),
                reason=f"BTC momentum up {momentum:+.2f}% → YES on above ${closest_otm.strike:,}",
                btc_price=btc_price,
                btc_momentum_5m=momentum,
            ))

    # --- Signal B: BTC trending DOWN → buy NO on closest ITM ---
    # The ITM YES is expensive (e.g. 0.80) because BTC is still above strike.
    # Buying NO at 0.20 bets BTC will fall below the strike by noon.
    if closest_itm and momentum <= -min_mom:
        no = closest_itm.no_price
        if otm_min <= no <= otm_max:
            signals.append(TradeSignal(
                condition_id=closest_itm.condition_id,
                question=closest_itm.question,
                strike=closest_itm.strike,
                side="NO",
                entry_price=no,
                take_profit=min(no + tp_delta, 0.95),
                stop_loss=max(no - sl_delta, 0.01),
                reason=f"BTC momentum down {momentum:+.2f}% → NO on above ${closest_itm.strike:,}",
                btc_price=btc_price,
                btc_momentum_5m=momentum,
            ))

    # --- Signal C: Fade extreme moves (mean reversion) ---
    # When BTC has moved hard in one direction and the OTM YES is at 1-5%,
    # there's often a bounce. Fade the move by buying the cheap YES on downside strikes.
    if closest_itm and momentum >= min_mom * 3:
        # BTC is surging — the strike ABOVE current might have a YES that's dirt cheap
        # because it was set when BTC was lower. Check if it's mispriced.
        yes = closest_itm.yes_price
        if yes > 0.90:  # deeply ITM — not interesting
            pass
    # (Reversion signals can be added later based on live data analysis)

    return signals


def should_exit(
    side: str,
    entry_price: float,
    current_yes_price: float,
    take_profit: float,
    stop_loss: float,
    hours_to_expiry: float,
) -> tuple[bool, str]:
    """
    Determine if an open position should be exited.
    Returns (should_exit, reason).
    """
    # Force-exit approaching expiry to avoid binary outcome risk
    if hours_to_expiry < 0.5:
        return True, "expiry_approaching"

    if side == "YES":
        if current_yes_price >= take_profit:
            return True, "take_profit"
        if current_yes_price <= stop_loss:
            return True, "stop_loss"
    else:  # NO
        current_no_price = 1 - current_yes_price
        if current_no_price >= take_profit:
            return True, "take_profit"
        if current_no_price <= stop_loss:
            return True, "stop_loss"

    return False, ""
