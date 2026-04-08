"""
Chainlink price feed via Polygon RPC — asset-aware, class-based.

Each asset (BTC, ETH, SOL, XRP) has its own ChainlinkFeed instance running
a background thread that polls its aggregator contract every 2s.

Contracts verified on Polygon 2026-04-05:
  BTC/USD: 0xc907E116054Ad103354f2D350FD2514433D57F6F  ~$68,837
  ETH/USD: 0xF9680D99D6C9589e2a93a78A04A279e509205945  ~$2,116
  SOL/USD: 0x10C8264C0935b3B9870013e057f330Ff3e9C56dC  ~$82
  XRP/USD: 0x785ba89291f676b5386652eB12b30cF361020694  ~$1.33
"""
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass

import httpx

CHAINLINK_CONTRACTS: dict[str, str] = {
    "BTC": "0xc907E116054Ad103354f2D350FD2514433D57F6F",
    "ETH": "0xF9680D99D6C9589e2a93a78A04A279e509205945",
    "SOL": "0x10C8264C0935b3B9870013e057f330Ff3e9C56dC",
    "XRP": "0x785ba89291f676b5386652eB12b30cF361020694",
}

# Minimum sane price per asset — rejects garbage RPC responses
ASSET_MIN_PRICE: dict[str, float] = {
    "BTC": 1_000.0,
    "ETH": 50.0,
    "SOL": 5.0,
    "XRP": 0.05,
}

POLYGON_RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.drpc.org",
    "https://rpc.ankr.com/polygon",
]

POLL_INTERVAL = 2.0
SCALE = 1e8
LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"


@dataclass
class ChainlinkState:
    price: float = 0.0
    updated_at: float = 0.0
    window_start_price: float = 0.0
    window_start_ts: float = 0.0
    pct_change: float = 0.0
    prev_window_start_price: float = 0.0

    def is_stale(self, max_age: float = 15.0) -> bool:
        return time.time() - self.updated_at > max_age


def _eth_call(rpc: str, to: str, data: str) -> str | None:
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
    try:
        raw = hex_result[2:]  # strip "0x" only — lstrip("0x") strips leading zeros too
        if len(raw) < 128:
            return None
        answer = int(raw[64:128], 16)
        return answer / SCALE
    except Exception:
        return None


class ChainlinkFeed:
    """Per-asset Chainlink price feed running in its own background thread."""

    def __init__(self, asset: str = "BTC") -> None:
        self.asset = asset.upper()
        self.contract = CHAINLINK_CONTRACTS.get(self.asset, "")
        self.min_price = ASSET_MIN_PRICE.get(self.asset, 0.01)
        self._lock = threading.Lock()
        self._state = ChainlinkState()
        self._thread: threading.Thread | None = None
        self._running = False
        self._rpc_index = 0

    def _fetch_price(self) -> float | None:
        if not self.contract:
            return None
        for _ in range(len(POLYGON_RPCS)):
            rpc = POLYGON_RPCS[self._rpc_index % len(POLYGON_RPCS)]
            result = _eth_call(rpc, self.contract, LATEST_ROUND_DATA_SELECTOR)
            if result:
                price = _decode_latest_round(result)
                if price and price > self.min_price:
                    return price
            self._rpc_index += 1
        return None

    def _run(self) -> None:
        print(f"[CHAINLINK-{self.asset}] Feed started — polling Polygon every 2s")
        while self._running:
            price = self._fetch_price()
            if price:
                now = time.time()
                with self._lock:
                    window_end = (int(now) // 300 + 1) * 300
                    window_start = window_end - 300
                    new_window = (self._state.window_start_ts < window_start)

                    if new_window:
                        prev_start = self._state.window_start_price
                        cross_pct = ((price - prev_start) / prev_start * 100) if prev_start > 0 else 0.0
                        print(
                            f"[CHAINLINK-{self.asset}] New window — "
                            f"start=${price:,.2f} prev=${prev_start:,.2f} cross={cross_pct:+.3f}%"
                        )
                        self._state.prev_window_start_price = prev_start
                        self._state.window_start_price = price
                        self._state.window_start_ts = window_start

                    pct = 0.0
                    if self._state.window_start_price > 0:
                        pct = (price - self._state.window_start_price) / self._state.window_start_price * 100

                    self._state.price = price
                    self._state.updated_at = now
                    self._state.pct_change = round(pct, 4)

            time.sleep(POLL_INTERVAL)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"chainlink-{self.asset.lower()}"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def get_state(self) -> ChainlinkState:
        with self._lock:
            return copy.copy(self._state)

    def wait_for_price(self, timeout: float = 15.0) -> ChainlinkState | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.get_state()
            if st.price > 0:
                return st
            time.sleep(0.5)
        return None
