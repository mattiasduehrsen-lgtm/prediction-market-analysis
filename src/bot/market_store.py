"""
Market data store — buffers raw feed data and flushes to daily Parquet files.

Market data is stored separately from paper trading results so it can be
analyzed, backtested, and shared cleanly.

Layout on disk:
  output/market_data/
    clob_events/   YYYY-MM-DD.parquet  — every Polymarket CLOB WebSocket event
    price_ticks/   YYYY-MM-DD.parquet  — UP/DOWN midpoint sampled every 5s
    chainlink/     YYYY-MM-DD.parquet  — Chainlink price polls (Polygon RPC)
    binance_spot/  YYYY-MM-DD.parquet  — Binance REST spot price, polled every 2s

All files use Snappy compression via PyArrow. Rows are buffered in memory and
flushed automatically every FLUSH_SECS seconds or when FLUSH_ROWS rows
accumulate. Call flush_all() on bot shutdown to flush any remaining rows.

Usage:
    from src.bot.market_store import CLOB_EVENTS, PRICE_TICKS, CHAINLINK, BINANCE_SPOT
    CLOB_EVENTS.append({"ts": ..., "event_type": ..., ...})
    flush_all()   # on shutdown
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pandas as pd

BASE_DIR    = Path("output/market_data")
FLUSH_ROWS  = 500     # flush after this many buffered rows
FLUSH_SECS  = 120     # flush at least this often (seconds)


class DataStore:
    """
    Thread-safe buffer that flushes to a daily Parquet file.

    One file per calendar day: output/market_data/{name}/YYYY-MM-DD.parquet
    If the day's file already exists (e.g. bot restarted mid-day), new rows
    are appended to it atomically via a write-to-temp + rename.
    """

    def __init__(self, name: str) -> None:
        self._name       = name
        self._dir        = BASE_DIR / name
        self._buffer:    list[dict] = []
        self._lock       = threading.Lock()
        self._last_flush = time.time()

    def append(self, row: dict) -> None:
        """Append one row. Triggers an automatic flush when thresholds are met."""
        with self._lock:
            self._buffer.append(row)
            if (len(self._buffer) >= FLUSH_ROWS or
                    time.time() - self._last_flush >= FLUSH_SECS):
                self._flush_locked()

    def flush(self) -> None:
        """Manually flush the buffer to disk (call on shutdown)."""
        with self._lock:
            self._flush_locked()

    # ── Internal ───────────────────────────────────────────────────────────────

    def _flush_locked(self) -> None:
        """Must be called with self._lock held."""
        if not self._buffer:
            return

        today = time.strftime("%Y-%m-%d")
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{today}.parquet"
        tmp  = self._dir / f"{today}.tmp.parquet"

        df_new = pd.DataFrame(self._buffer)

        try:
            if path.exists():
                df_existing = pd.read_parquet(path)
                df_out = pd.concat([df_existing, df_new], ignore_index=True)
            else:
                df_out = df_new

            df_out.to_parquet(tmp, engine="pyarrow", compression="snappy", index=False)
            os.replace(tmp, path)   # atomic on both Linux and Windows
        except Exception as exc:
            print(f"[MARKET STORE] Flush error ({self._name}): {exc}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return

        self._buffer.clear()
        self._last_flush = time.time()


# ── Module-level store instances ───────────────────────────────────────────────
# Import these directly in feed modules — no need to pass instances around.

CLOB_EVENTS  = DataStore("clob_events")   # Polymarket CLOB WebSocket events
PRICE_TICKS  = DataStore("price_ticks")   # UP/DOWN midpoint, every 5s
CHAINLINK    = DataStore("chainlink")     # Chainlink on-chain price polls
BINANCE_SPOT = DataStore("binance_spot")  # Binance REST spot prices


def flush_all() -> None:
    """Flush all stores to disk. Call this on clean bot shutdown."""
    for store in (CLOB_EVENTS, PRICE_TICKS, CHAINLINK, BINANCE_SPOT):
        store.flush()
    print("[MARKET STORE] All stores flushed to output/market_data/")
