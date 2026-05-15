"""
Phase 1 — microstructure snapshot at entry decision time.

Captures features that the static-filter cascade ignored:
  - Order book state (top-of-book prices, depth on each side, book imbalance)
  - CLOB trade flow over multiple lookback windows
  - Midpoint trend evolution
  - Realized volatility from local price history
  - Cross-asset Binance % moves over multiple windows

Writes one row to output/5m_trading/microstructure_features.csv per actual
entry, keyed by position_id (filled in by the engine once entry confirms).

NO bot decision changes — pure observation. After ~200 entries we run
analysis/ml_microstructure.py to test whether these features predict pnl.
"""
from __future__ import annotations

import csv as _csv
import statistics
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

_PATH = Path("output/5m_trading/microstructure_features.csv")
_LOCK = threading.Lock()

_COLUMNS = [
    "timestamp", "position_id", "asset", "window", "side",
    # Book
    "best_bid", "best_ask", "spread",
    "bid_depth", "ask_depth", "book_imbalance",
    # Midpoint trend
    "mid_trend_10s", "mid_trend_30s", "mid_trend_60s",
    # Trade flow
    "trades_10s", "trades_30s", "trades_60s",
    # Local price velocity / realized vol
    "rv_30s", "rv_60s",
    "vel_10s", "vel_30s", "vel_60s",
    # Cross-asset Binance moves
    "btc_pct_30s", "btc_pct_60s", "btc_pct_300s",
    "binance_now",
    # Bookkeeping
    "entry_price", "secs_into_window",
]


@dataclass
class MicroSnapshot:
    """Single snapshot of decision-time microstructure state."""
    timestamp: float
    position_id: str
    asset: str
    window: str
    side: str
    best_bid: float
    best_ask: float
    spread: float
    bid_depth: float
    ask_depth: float
    book_imbalance: float
    mid_trend_10s: float
    mid_trend_30s: float
    mid_trend_60s: float
    trades_10s: int
    trades_30s: int
    trades_60s: int
    rv_30s: float
    rv_60s: float
    vel_10s: float
    vel_30s: float
    vel_60s: float
    btc_pct_30s: float
    btc_pct_60s: float
    btc_pct_300s: float
    binance_now: float
    entry_price: float
    secs_into_window: float


def _rv(history, lookback_secs: float) -> float:
    """Realized vol = stdev of cheap-side prices in the lookback window."""
    if not history or len(history) < 3:
        return 0.0
    now = time.time()
    cutoff = now - lookback_secs
    prices = [p for ts, p in history if ts >= cutoff and p > 0]
    if len(prices) < 3:
        return 0.0
    try:
        return round(statistics.stdev(prices), 6)
    except statistics.StatisticsError:
        return 0.0


def _velocity(history, lookback_secs: float) -> float:
    """Average price change per second over the lookback."""
    if not history or len(history) < 2:
        return 0.0
    now = time.time()
    cutoff = now - lookback_secs
    in_window = [(ts, p) for ts, p in history if ts >= cutoff and p > 0]
    if len(in_window) < 2:
        return 0.0
    dt = in_window[-1][0] - in_window[0][0]
    if dt <= 0:
        return 0.0
    return round((in_window[-1][1] - in_window[0][1]) / dt, 6)


def _binance_pct(binance_history, lookback_secs: float, current: float) -> float:
    """Percent change vs `current` Binance price `lookback_secs` ago."""
    if not binance_history or current <= 0:
        return 0.0
    now = time.time()
    cutoff = now - lookback_secs
    in_window = [(ts, p) for ts, p in binance_history if ts <= cutoff and p > 0]
    if not in_window:
        return 0.0
    past = in_window[-1][1]
    if past <= 0:
        return 0.0
    return round((current - past) / past * 100.0, 4)


def capture(
    asset: str,
    window: str,
    side: str,
    entry_price: float,
    secs_into_window: float,
    clob_feed=None,
    price_history=None,   # local cheap-side price history: list[(ts, price)]
    binance_feed=None,
    binance_history=None,  # list[(ts, price)] from main loop
) -> MicroSnapshot:
    """
    Build a microstructure snapshot. Caller passes the components it already
    has — this function ONLY reads, no I/O. Returns the dataclass.
    """
    now = time.time()

    # Book state
    bb = ba = spread = bid_depth = ask_depth = 0.0
    book_imb = 0.5
    mt10 = mt30 = mt60 = 0.0
    tr10 = tr30 = tr60 = 0
    if clob_feed is not None:
        try:
            bb, ba, spread, bid_depth, ask_depth = clob_feed.get_book_state()
            total_depth = bid_depth + ask_depth
            if total_depth > 0:
                book_imb = round(bid_depth / total_depth, 4)
            mt10 = clob_feed.get_midpoint_trend(10.0)
            mt30 = clob_feed.get_midpoint_trend(30.0)
            mt60 = clob_feed.get_midpoint_trend(60.0)
            tr10 = clob_feed.get_recent_trade_count(10.0)
            tr30 = clob_feed.get_recent_trade_count(30.0)
            tr60 = clob_feed.get_recent_trade_count(60.0)
        except Exception:
            pass

    rv30 = _rv(price_history, 30.0)
    rv60 = _rv(price_history, 60.0)
    vel10 = _velocity(price_history, 10.0)
    vel30 = _velocity(price_history, 30.0)
    vel60 = _velocity(price_history, 60.0)

    binance_now = 0.0
    if binance_feed is not None:
        try:
            binance_now = float(binance_feed.get() or 0.0)
        except Exception:
            pass

    btc30  = _binance_pct(binance_history, 30.0, binance_now)
    btc60  = _binance_pct(binance_history, 60.0, binance_now)
    btc300 = _binance_pct(binance_history, 300.0, binance_now)

    return MicroSnapshot(
        timestamp=now, position_id="", asset=asset.upper(), window=window, side=side,
        best_bid=bb, best_ask=ba, spread=spread,
        bid_depth=bid_depth, ask_depth=ask_depth, book_imbalance=book_imb,
        mid_trend_10s=mt10, mid_trend_30s=mt30, mid_trend_60s=mt60,
        trades_10s=tr10, trades_30s=tr30, trades_60s=tr60,
        rv_30s=rv30, rv_60s=rv60,
        vel_10s=vel10, vel_30s=vel30, vel_60s=vel60,
        btc_pct_30s=btc30, btc_pct_60s=btc60, btc_pct_300s=btc300,
        binance_now=binance_now,
        entry_price=entry_price,
        secs_into_window=round(secs_into_window, 1),
    )


def write(snapshot: MicroSnapshot, position_id: str) -> None:
    """Append one snapshot row. Caller fills in position_id after entry confirms."""
    snapshot.position_id = position_id
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            need_header = not _PATH.exists() or _PATH.stat().st_size == 0
            with _PATH.open("a", encoding="utf-8", newline="") as fh:
                w = _csv.DictWriter(fh, fieldnames=_COLUMNS)
                if need_header:
                    w.writeheader()
                row = asdict(snapshot)
                w.writerow({k: row.get(k, "") for k in _COLUMNS})
    except Exception as e:
        print(f"  [MICRO] write error: {e}")
