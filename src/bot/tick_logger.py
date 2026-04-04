"""
Price tick logger — persists UP/DOWN prices every 5 seconds to disk.

Output: output/5m_trading/price_ticks.csv
Appends continuously. Each row is one tick.

Fields:
  ts            — unix timestamp of the tick
  condition_id  — Polymarket condition ID (identifies the 5-min window)
  slug          — human-readable market slug
  up_price      — CLOB midpoint for the UP token
  down_price    — CLOB midpoint for the DOWN token
  seconds_left  — seconds remaining in the window at tick time
  source        — "clob" (live) or "cached" (CLOB unavailable, last known price)

Use for backtesting: replay ticks to simulate any ENTRY_MIN/ENTRY_MAX/timing combo.
At 5s intervals: ~60 ticks per 5-min window, ~720 ticks/hour, ~17,280 ticks/day (~1MB/day).
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

TICKS_FILE  = Path("output/5m_trading/price_ticks.csv")
TICK_FIELDS = [
    "ts", "condition_id", "slug",
    "up_price", "down_price", "seconds_left", "source",
]
TICK_INTERVAL = 5   # seconds between logged ticks


class TickLogger:
    """Call .tick() on every poll; internally throttles to TICK_INTERVAL seconds."""

    def __init__(self) -> None:
        TICKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._last_logged: float = 0.0
        self._write_header = not TICKS_FILE.exists()

    def tick(
        self,
        condition_id: str,
        slug: str,
        up_price: float,
        down_price: float,
        seconds_left: float,
        source: str = "clob",
    ) -> None:
        now = time.time()
        if now - self._last_logged < TICK_INTERVAL:
            return
        self._last_logged = now

        with open(TICKS_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TICK_FIELDS)
            if self._write_header:
                writer.writeheader()
                self._write_header = False
            writer.writerow({
                "ts":           round(now, 2),
                "condition_id": condition_id,
                "slug":         slug,
                "up_price":     round(up_price, 4),
                "down_price":   round(down_price, 4),
                "seconds_left": round(seconds_left, 1),
                "source":       source,
            })
