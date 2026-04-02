"""
Chainlink BTC/USD price feed via Polygon RPC.

Polymarket's 5-minute Up/Down markets resolve against the Chainlink BTC/USD
price stream on Polygon. The window "start price" is the Chainlink price at
the exact moment the 5-minute window opens — this is the actual reference
price, not anything from Binance or the Gamma API.

Strategy: poll the Chainlink aggregator contract every 2 seconds.
  - Track window start price (recorded when a new window begins)
  - Compute % change from start price to now
  - Use this to confirm or fade entries based on actual move size

Contract: BTC/USD on Polygon
  Address: 0xc907E116054Ad103354f2D350FD2514433D57F6F
  Function: latestRoundData() → (roundId, answer, startedAt, updatedAt, answeredInRound)
  answer is scaled by 1e8 (divide by 1e8 to get USD price)

Public Polygon RPC (no key needed):
  https://polygon-rpc.com
  https://rpc.ankr.com/polygon
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import httpx

# Chainlink BTC/USD aggregator on Polygon
CHAINLINK_CONTRACT = "0xc907E116054Ad103354f2D350FD2514433D57F6F"
POLYGON_RPCS = [
    "https://polygon-rpc.com",
    "https://rpc.ankr.com/polygon",
    "https://polygon.llamarpc.com",
]

POLL_INTERVAL = 2.0   # seconds between Chainlink polls
SCALE = 1e8           # Chainlink answer is price * 1e8

# ABI call for latestRoundData() — keccak256("latestRoundData()") = 0xfeaf968c
LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"


@dataclass
class ChainlinkState:
    price: float = 0.0
    updated_at: float = 0.0       # unix ts of last successful poll
    window_start_price: float = 0.0   # price at start of current 5m window
    window_start_ts: float = 0.0
    pct_change: float = 0.0       # % change since window opened

    def is_stale(self, max_age: float = 15.0) -> bool:
        return time.time() - self.updated_at > max_age


_lock  = threading.Lock()
_state = ChainlinkState()
_thread: threading.Thread | None = None
_running = False
_rpc_index = 0


def _eth_call(rpc: str, to: str, data: str) -> str | None:
    """Make a raw eth_call JSON-RPC request."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
        "id": 1,
    }
    try:
        r = httpx.post(rpc, json=payload, timeout=5)
        result = r.json().get("result", "")
        return result if result and result != "0x" else None
    except Exception:
        return None


def _decode_latest_round(hex_result: str) -> float | None:
    """Decode the latestRoundData() return value and extract the price."""
    # Returns 5 x uint256 packed: roundId, answer, startedAt, updatedAt, answeredInRound
    # Each uint256 is 32 bytes (64 hex chars). We want [1] = answer.
    try:
        raw = hex_result.lstrip("0x")
        if len(raw) < 128:  # need at least 2 x 32-byte words
            return None
        answer_hex = raw[64:128]   # second 32-byte word
        answer = int(answer_hex, 16)
        return answer / SCALE
    except Exception:
        return None


def _fetch_price() -> float | None:
    """Try each RPC in order until one works."""
    global _rpc_index
    for _ in range(len(POLYGON_RPCS)):
        rpc = POLYGON_RPCS[_rpc_index % len(POLYGON_RPCS)]
        result = _eth_call(rpc, CHAINLINK_CONTRACT, LATEST_ROUND_DATA_SELECTOR)
        if result:
            price = _decode_latest_round(result)
            if price and price > 1000:  # sanity check — BTC > $1000
                return price
        _rpc_index += 1
    return None


def _run() -> None:
    global _state, _running
    print("[CHAINLINK] Feed started — polling Polygon every 2s")
    while _running:
        price = _fetch_price()
        if price:
            now = time.time()
            with _lock:
                # Detect new 5m window: window_end is next multiple of 300
                window_end = (int(now) // 300 + 1) * 300
                window_start = window_end - 300
                new_window = (_state.window_start_ts < window_start)

                if new_window:
                    _state.window_start_price = price
                    _state.window_start_ts = window_start
                    print(f"[CHAINLINK] New window — start price ${price:,.2f}")

                pct = 0.0
                if _state.window_start_price > 0:
                    pct = (price - _state.window_start_price) / _state.window_start_price * 100

                _state = ChainlinkState(
                    price=price,
                    updated_at=now,
                    window_start_price=_state.window_start_price,
                    window_start_ts=_state.window_start_ts,
                    pct_change=round(pct, 4),
                )
        time.sleep(POLL_INTERVAL)


def start() -> None:
    global _thread, _running
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_run, daemon=True, name="chainlink-feed")
    _thread.start()


def stop() -> None:
    global _running
    _running = False


def get_state() -> ChainlinkState:
    with _lock:
        import copy
        return copy.copy(_state)


def wait_for_price(timeout: float = 15.0) -> ChainlinkState | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = get_state()
        if s.price > 0:
            return s
        time.sleep(0.5)
    return None
