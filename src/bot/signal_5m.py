"""
Signal engine for 5m/15m Up/Down markets.

Two strategies:
  mean_reversion — buy cheap side (28-39¢), bet on reversal within window
  momentum       — enter at window open, bet same direction as previous window (PolyBackTest edge)
"""
from __future__ import annotations

import math
import os

from src.bot.market_5m import (
    Market5m,
    ENTRY_MIN, ENTRY_MAX, TAKE_PROFIT,
    MIN_SECONDS, FORCE_EXIT, SOFT_EXIT_SECS, SOFT_EXIT_PRICE,
    BTC_SKIP_RATE, BTC_MAGNITUDE_MAX, MAX_SPREAD, MIN_LIQUIDITY,
    MOMENTUM_ENTRY_WINDOW, MOMENTUM_MIN_PREV_MOVE, MOMENTUM_ENABLED,
    CROSS_WINDOW_MIN, CROSS_WINDOW_MAX,
)


def should_enter(
    market: Market5m,
    btc_rate_per_min: float = 0.0,
    cl_pct_change: float = 0.0,
    min_seconds: float = MIN_SECONDS,
    spread: float = 0.0,
    cross_window_pct: float = 0.0,
    secs_into_window: float = 0.0,    # seconds elapsed since window start
    clob_trades_60s: int = 0,         # CLOB last_trade_price events in last 60s
) -> tuple[bool, str, float]:
    """
    Mean-reversion entry: buy the cheap side (ENTRY_MIN–ENTRY_MAX) in the entry window.
    Returns (should_enter, side, entry_price).
    Asset-specific filters derived from Cowork analysis of 698 trades.
    """
    secs = market.seconds_remaining

    if secs < min_seconds:
        return False, "", 0.0

    if market.liquidity < MIN_LIQUIDITY:
        print(f"[SIGNAL] Skip — liquidity ${market.liquidity:,.0f} < ${MIN_LIQUIDITY:,} (thin market)")
        return False, "", 0.0

    # Spread filter: skip when the order book is too wide (illiquid or stale prices).
    # spread=0 means the WebSocket feed isn't ready yet — don't block on that.
    if spread > 0 and spread > MAX_SPREAD:
        print(f"[SIGNAL] Skip — spread {spread:.4f} > {MAX_SPREAD} (illiquid)")
        return False, "", 0.0

    # Cross-window filter: only enter on small prior-window dips.
    # cross_window=0.0 means no Chainlink data yet — pass through.
    # Data: [-0.05,0] = 40.5% WR; all other bands ≤27% WR and negative EV.
    if cross_window_pct != 0.0:
        if cross_window_pct < CROSS_WINDOW_MIN or cross_window_pct > CROSS_WINDOW_MAX:
            print(f"[SIGNAL] Skip — cross_window {cross_window_pct:+.3f}% outside [{CROSS_WINDOW_MIN},{CROSS_WINDOW_MAX}]")
            return False, "", 0.0

    # Cheaper side is our mean-reversion candidate
    if market.up_price <= market.down_price:
        side, price = "UP", market.up_price
    else:
        side, price = "DOWN", market.down_price

    if price < ENTRY_MIN or price > ENTRY_MAX:
        return False, "", 0.0

    # ── Asset-specific filters (Cowork analysis) ──────────────────────────
    asset = market.asset
    window = market.window

    # SOL-15m: DOWN trades are losing (-$73); UP only (+$88)
    if asset == "SOL" and window == "15m":
        if side == "DOWN":
            print(f"[SIGNAL] Skip SOL DOWN — only UP side is profitable (+$88 vs -$73)")
            return False, "", 0.0
        if price > 0.35:
            print(f"[SIGNAL] Skip SOL — entry {price:.3f} > 0.35 (loses money in high band)")
            return False, "", 0.0

    # ETH-15m: 0.30-0.35 band loses $165; 0.35-0.40 zone wins +$40 on 21 trades
    # Cowork (133 trades, Apr 10-13): first 30s hits 54.5% WR vs 24.0% after (p=0.040)
    # Crowded book (>5 CLOB trades/60s) → 28.6% WR vs 66.7% (p=0.037)
    if asset == "ETH" and window == "15m":
        if price < 0.35:
            print(f"[SIGNAL] Skip ETH — entry {price:.3f} < 0.35 (loss zone)")
            return False, "", 0.0
        if secs_into_window > 30:
            print(f"[SIGNAL] Skip ETH-15m — {secs_into_window:.0f}s into window (>30s cutoff, WR drops to 24%)")
            return False, "", 0.0
        if clob_trades_60s > 5:
            print(f"[SIGNAL] Skip ETH-15m — {clob_trades_60s} CLOB trades in 60s (crowded, WR 28.6%)")
            return False, "", 0.0

    # BTC-5m: prefer 0.33-0.40; skip high liquidity (overcrowded)
    if asset == "BTC" and window == "5m":
        if secs < 292:
            print(f"[SIGNAL] Skip BTC-5m — late entry ({secs:.0f}s remaining, dead zone 240–290)")
            return False, "", 0.0
        if not (0.33 <= price <= 0.40):
            print(f"[SIGNAL] Skip BTC-5m — entry {price:.3f} outside 0.33–0.40 sweet spot")
            return False, "", 0.0
        if market.liquidity >= 17_000:
            print(f"[SIGNAL] Skip BTC-5m — liquidity ${market.liquidity:,.0f} >= $17k (overcrowded)")
            return False, "", 0.0

    # BTC-15m: only 0.35-0.40 zone is profitable (+$14 on 17 trades)
    if asset == "BTC" and window == "15m":
        if not (0.35 <= price <= 0.40):
            print(f"[SIGNAL] Skip BTC-15m — entry {price:.3f} outside 0.35–0.40")
            return False, "", 0.0

    # Magnitude filter: only applies to BTC 5m — threshold was calibrated for BTC.
    # ETH/SOL/XRP and 15m markets move differently; skip the filter for them.
    if market.asset == "BTC" and market.window == "5m":
        if cl_pct_change != 0.0 and abs(cl_pct_change) > BTC_MAGNITUDE_MAX:
            print(f"[SIGNAL] Skip — BTC move too large: {cl_pct_change:+.3f}% (max ±{BTC_MAGNITUDE_MAX}%)")
            return False, "", 0.0

    # BTC momentum filter: skip if asset is moving hard against our side
    if side == "UP" and btc_rate_per_min < -BTC_SKIP_RATE:
        print(f"[SIGNAL] Skip UP — {market.asset} falling ${btc_rate_per_min:.1f}/min (threshold -${BTC_SKIP_RATE}/min)")
        return False, "", 0.0
    if side == "DOWN" and btc_rate_per_min > BTC_SKIP_RATE:
        print(f"[SIGNAL] Skip DOWN — {market.asset} rising ${btc_rate_per_min:.1f}/min (threshold +${BTC_SKIP_RATE}/min)")
        return False, "", 0.0

    return True, side, price


def should_enter_resolution_scalp(
    market: "Market5m",
    btc_at_window_start: float,
    btc_now: float,
    rv_std: float,
) -> tuple[bool, str, float]:
    """
    Resolution-edge scalp (Cowork 2026-04-19 Strategy #4, 79% WR synthetic backtest).

    Enters in the last 10–90s of a 15m window when Binance has mathematically
    near-determined the outcome but Polymarket hasn't fully priced it in yet.

    Logic:
      - Compute GBM implied P(UP wins) from Binance path + remaining vol + τ.
      - BUY UP  if implied_p_up > RESSCALP_IMPLIED_MIN  and
                   up_price < implied_p_up - RESSCALP_GAP_MIN
      - BUY DOWN if implied_p_up < (1 - RESSCALP_IMPLIED_MIN) and
                   down_price < (1 - implied_p_up) - RESSCALP_GAP_MIN

    No TP or SL — position holds to force_exit_time (~5s before window end).

    Args:
        market:              current market snapshot
        btc_at_window_start: Binance price at window open
        btc_now:             current Binance price
        rv_std:              per-2s-bar log-return std (from 15-min history)

    Env overrides:
        RESSCALP_IMPLIED_MIN  (default 0.75)
        RESSCALP_GAP_MIN      (default 0.05)
    """
    secs = market.seconds_remaining

    # Entry window: last 10–90s of the 15m window
    if not (10.0 < secs < 90.0):
        return False, "", 0.0

    if btc_at_window_start <= 0 or btc_now <= 0 or rv_std <= 0:
        return False, "", 0.0

    if market.liquidity < MIN_LIQUIDITY:
        return False, "", 0.0

    # GBM implied P(UP wins): Φ( ln(btc_now / btc_wstart) / (σ·√τ) )
    tau     = max(1.0, float(secs))
    sig_tau = (rv_std / math.sqrt(2.0)) * math.sqrt(tau)
    if sig_tau <= 0:
        return False, "", 0.0

    try:
        z            = math.log(btc_now / btc_at_window_start) / sig_tau
        implied_p_up = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    except (ValueError, ZeroDivisionError):
        return False, "", 0.0

    IMPLIED_MIN = float(os.environ.get("RESSCALP_IMPLIED_MIN", "0.75"))
    GAP_MIN     = float(os.environ.get("RESSCALP_GAP_MIN",     "0.05"))

    if implied_p_up > IMPLIED_MIN:
        gap = implied_p_up - market.up_price
        if gap >= GAP_MIN and market.up_price < 0.95:
            print(
                f"[RESSCALP] UP @ {market.up_price:.3f} | "
                f"implied_p={implied_p_up:.3f} gap={gap:+.3f} secs={secs:.0f}s"
            )
            return True, "UP", market.up_price

    if implied_p_up < (1.0 - IMPLIED_MIN):
        p_down = 1.0 - implied_p_up
        gap    = p_down - market.down_price
        if gap >= GAP_MIN and market.down_price < 0.95:
            print(
                f"[RESSCALP] DOWN @ {market.down_price:.3f} | "
                f"implied_p_down={p_down:.3f} gap={gap:+.3f} secs={secs:.0f}s"
            )
            return True, "DOWN", market.down_price

    return False, "", 0.0


def should_enter_momentum(
    market: Market5m,
    cross_window_pct: float,
    min_prev_move: float = MOMENTUM_MIN_PREV_MOVE,
) -> tuple[bool, str, float]:
    if not MOMENTUM_ENABLED:
        return False, "", 0.0
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

    # UP-only: UP momentum 45% WR vs DOWN 29% WR (28 trades) — DOWN is marginal at best
    if cross_window_pct <= 0:
        return False, "", 0.0

    side  = "UP"
    price = market.up_price

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


def take_profit_price(entry_price: float) -> float | None:
    """
    Returns the take-profit target for this entry price, or None to skip the trade.

    Replaces fixed TAKE_PROFIT=0.92 with an entry-price-dependent formula derived
    from Cowork analysis of 685 paper trades (2026-04-11):
      entry ≤ 0.32 → TP 0.63   (+97–127% gain needed)
      entry ≤ 0.36 → TP 0.62   (+72–82%)
      entry ≤ 0.40 → TP 0.60   (+50–67%)
      entry ≤ 0.42 → TP 0.59   (+40–48%)
      entry  > 0.42 → None (skip — negative EV above 0.42)
    Simulated full-dataset PnL: +$2,108 vs −$1,073 actual (65% vs 39% WR).
    """
    from src.bot.tp_optimizer import compute_take_profit
    return compute_take_profit(entry_price)
