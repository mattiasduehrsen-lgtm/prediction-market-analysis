"""
Price tick logger — persists UP/DOWN midpoint prices every 5 seconds.

Output:
  output/market_data/price_ticks/YYYY-MM-DD.parquet  (Snappy-compressed)

Fields:
  ts            — unix timestamp of the tick
  condition_id  — Polymarket condition ID (identifies the 5-min window)
  slug          — human-readable market slug
  up_price      — CLOB midpoint for the UP token
  down_price    — CLOB midpoint for the DOWN token
  seconds_left  — seconds remaining in the window at tick time
  source        — "ws" (WebSocket feed) | "rest" (REST poll) | "cached"

At 5s intervals: ~60 ticks per 5-min window, ~720 ticks/hour, ~17,280 ticks/day.
Use for backtesting: replay ticks to simulate any ENTRY_MIN/ENTRY_MAX/timing combo.
"""
from __future__ import annotations

import time

from src.bot.market_store import PRICE_TICKS

TICK_INTERVAL = 5   # seconds between logged ticks


class TickLogger:
    """Call .tick() on every poll; internally throttles to TICK_INTERVAL seconds."""

    def __init__(self) -> None:
        self._last_logged: float = 0.0

    def tick(
        self,
        condition_id: str,
        slug: str,
        up_price: float,
        down_price: float,
        seconds_left: float,
        source: str = "rest",
    ) -> None:
        now = time.time()
        if now - self._last_logged < TICK_INTERVAL:
            return
        self._last_logged = now

        PRICE_TICKS.append({
            "ts":           round(now, 2),
            "condition_id": condition_id,
            "slug":         slug,
            "up_price":     round(up_price,    4),
            "down_price":   round(down_price,  4),
            "seconds_left": round(seconds_left, 1),
            "source":       source,
        })
