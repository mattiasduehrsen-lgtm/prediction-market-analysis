"""
Real-time BTC price feed from Binance WebSocket.

Maintains a rolling window of recent prices to compute:
  - current price
  - 1-min momentum (% change over last 60s)
  - 5-min momentum (% change over last 300s)
  - direction: "up" | "down" | "flat"
  - volatility: std dev of last N ticks

Runs in a background thread. Call get_state() from any thread.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

import websocket  # websocket-client


BINANCE_WS = "wss://stream.binance.com:9443/ws/btcusdt@trade"
RECONNECT_DELAY = 5   # seconds between reconnect attempts
MAX_TICKS = 1000      # rolling window size


@dataclass
class PriceTick:
    ts: float    # unix timestamp
    price: float


@dataclass
class BTCState:
    price: float = 0.0
    momentum_1m: float = 0.0    # % change over 1 min
    momentum_5m: float = 0.0    # % change over 5 min
    momentum_15m: float = 0.0   # % change over 15 min
    direction: str = "flat"     # "up" | "down" | "flat"
    last_updated: float = 0.0
    connected: bool = False

    def is_stale(self, max_age: float = 30.0) -> bool:
        return time.time() - self.last_updated > max_age


_lock   = threading.Lock()
_ticks: Deque[PriceTick] = deque(maxlen=MAX_TICKS)
_state  = BTCState()
_thread: threading.Thread | None = None
_running = False


def _momentum(now_price: float, seconds_back: float) -> float:
    """% change from `seconds_back` seconds ago to now."""
    cutoff = time.time() - seconds_back
    old = None
    for tick in _ticks:
        if tick.ts >= cutoff:
            old = tick
            break
    if old is None or old.price == 0:
        return 0.0
    return (now_price - old.price) / old.price * 100


def _update_state(price: float) -> None:
    global _state
    tick = PriceTick(ts=time.time(), price=price)
    with _lock:
        _ticks.append(tick)
        m1  = _momentum(price, 60)
        m5  = _momentum(price, 300)
        m15 = _momentum(price, 900)

        if m5 > 0.1:
            direction = "up"
        elif m5 < -0.1:
            direction = "down"
        else:
            direction = "flat"

        _state = BTCState(
            price=price,
            momentum_1m=round(m1, 4),
            momentum_5m=round(m5, 4),
            momentum_15m=round(m15, 4),
            direction=direction,
            last_updated=time.time(),
            connected=True,
        )


def _on_message(ws, message: str) -> None:
    try:
        data = json.loads(message)
        price = float(data.get("p", 0))
        if price > 0:
            _update_state(price)
    except Exception:
        pass


def _on_error(ws, error) -> None:
    print(f"[BTC FEED] WebSocket error: {error}")


def _on_close(ws, close_status_code, close_msg) -> None:
    with _lock:
        _state.connected = False
    print("[BTC FEED] WebSocket closed")


def _on_open(ws) -> None:
    print("[BTC FEED] WebSocket connected to Binance")


def _run_forever() -> None:
    global _running
    while _running:
        try:
            ws = websocket.WebSocketApp(
                BINANCE_WS,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
                on_open=_on_open,
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as exc:
            print(f"[BTC FEED] Connection error: {exc}")

        if _running:
            print(f"[BTC FEED] Reconnecting in {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)


def start() -> None:
    """Start the background WebSocket feed. Safe to call multiple times."""
    global _thread, _running
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_run_forever, daemon=True, name="btc-feed")
    _thread.start()
    print("[BTC FEED] Started")


def stop() -> None:
    global _running
    _running = False


def get_state() -> BTCState:
    """Return the latest BTC state. Thread-safe."""
    with _lock:
        import copy
        return copy.copy(_state)


def wait_for_price(timeout: float = 10.0) -> BTCState | None:
    """Block until we have a valid price or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = get_state()
        if s.price > 0:
            return s
        time.sleep(0.2)
    return None
