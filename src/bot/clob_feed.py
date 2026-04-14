"""
Polymarket CLOB WebSocket feed.

Maintains a live order book for an UP/DOWN token pair, replacing the 2s
REST midpoint poll with true event-driven price updates.

Three event types are processed:
  book             — full order book snapshot   → sets best bid/ask/midpoint
  price_change     — individual level changed   → updates best bid/ask/midpoint
  last_trade_price — a trade was executed       → logged as a fill event

Every event is appended to:
  output/market_data/clob_events/YYYY-MM-DD.parquet  (Snappy-compressed)

Usage:
    feed = ClobFeed()
    feed.start()
    feed.subscribe(
        token_id_up="...", token_id_down="...",
        condition_id="...", slug="...", window_end_ts=1234567890.0
    )
    up, down, is_live = feed.get_prices()   # thread-safe; is_live=False = not ready
    feed.subscribe(...)                      # call again when window changes → auto-reconnect
    feed.stop()
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import websocket  # websocket-client

from src.bot.market_store import CLOB_EVENTS

CLOB_WS         = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
RECONNECT_DELAY = 5       # seconds between reconnect attempts


# ── Per-token order book ───────────────────────────────────────────────────────

@dataclass
class _TokenState:
    """Maintains a live order book and derived prices for a single token."""
    bids: dict = field(default_factory=dict)   # price_str → float size
    asks: dict = field(default_factory=dict)   # price_str → float size
    best_bid:  float = 0.0
    best_ask:  float = 1.0
    midpoint:  float = 0.5
    last_updated: float = 0.0
    # Rolling 120s of (timestamp, midpoint) for trend computation
    midpoint_history: deque = field(default_factory=lambda: deque(maxlen=120))

    def _recompute(self) -> None:
        if self.bids:
            self.best_bid = max(float(p) for p in self.bids)
        if self.asks:
            self.best_ask = min(float(p) for p in self.asks)
        if self.bids and self.asks:
            self.midpoint = round((self.best_bid + self.best_ask) / 2, 6)
        self.last_updated = time.time()
        self.midpoint_history.append((self.last_updated, self.midpoint))

    def apply_book(self, bids: list, asks: list) -> None:
        """Replace the full order book from a snapshot."""
        self.bids = {}
        self.asks = {}
        for b in bids:
            s = float(b.get("size", 0))
            if s > 0:
                self.bids[str(b["price"])] = s
        for a in asks:
            s = float(a.get("size", 0))
            if s > 0:
                self.asks[str(a["price"])] = s
        self._recompute()

    def apply_price_change(self, changes: list) -> None:
        """Apply incremental order book changes (size=0 removes the level)."""
        for ch in changes:
            price_str = str(ch.get("price", ""))
            size  = float(ch.get("size", 0))
            side  = ch.get("side", "").upper()
            if not price_str:
                continue
            if side == "BUY":
                if size <= 0:
                    self.bids.pop(price_str, None)
                else:
                    self.bids[price_str] = size
            elif side == "SELL":
                if size <= 0:
                    self.asks.pop(price_str, None)
                else:
                    self.asks[price_str] = size
        self._recompute()


# ── Feed ───────────────────────────────────────────────────────────────────────

class ClobFeed:
    """
    Real-time Polymarket CLOB feed via WebSocket.

    One instance per run_5m_loop thread. Falls back gracefully: if the
    WebSocket is not connected, get_prices() returns (0.5, 0.5, False) and
    the caller should use the REST midpoint poll instead.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Current subscription — updated by subscribe()
        self._token_id_up:   str   = ""
        self._token_id_down: str   = ""
        self._condition_id:  str   = ""
        self._slug:          str   = ""
        self._window_end_ts: float = 0.0

        # Per-token order book state
        self._states: dict[str, _TokenState] = {}

        # Rolling timestamps of last_trade_price events per token, for crowding detection
        self._trade_timestamps: dict[str, list] = {}

        # WebSocket
        self._ws:        websocket.WebSocketApp | None = None
        self._thread:    threading.Thread | None = None
        self._running:   bool = False
        self._connected: bool = False


    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background WebSocket thread. Safe to call multiple times."""
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_forever, daemon=True, name="clob-feed"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the feed. Safe to call from any thread."""
        self._running = False
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def subscribe(
        self,
        token_id_up:   str,
        token_id_down: str,
        condition_id:  str   = "",
        slug:          str   = "",
        window_end_ts: float = 0.0,
    ) -> None:
        """
        Switch to a new market. Resets order book state and triggers a
        WebSocket reconnect so the new token IDs are subscribed immediately.
        """
        with self._lock:
            self._token_id_up   = token_id_up
            self._token_id_down = token_id_down
            self._condition_id  = condition_id
            self._slug          = slug
            self._window_end_ts = window_end_ts
            # Fresh order book for the new window
            self._states[token_id_up]   = _TokenState()
            self._states[token_id_down] = _TokenState()

        # Force reconnect with the new token IDs (outside lock to avoid deadlock)
        ws = self._ws
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    def get_book_state(self) -> tuple[float, float, float, float, float]:
        """
        Return (best_bid, best_ask, spread, bid_depth_total, ask_depth_total)
        for the UP token's order book.

        best_bid / best_ask: top-of-book prices for the UP token.
        spread: best_ask - best_bid (0 = not ready).
        bid/ask_depth: total shares outstanding on each side.

        Used by the signal to filter wide-spread entries and to compute the
        realistic taker fill price (entry at best_ask, not midpoint).

        Single lock for the full operation — avoids TOCTOU race where the book
        changes between the first and second lock acquisitions (Finding 2.C).
        """
        with self._lock:
            up_id = self._token_id_up
            st    = self._states.get(up_id)
            if not (up_id and st and st.last_updated > 0 and st.best_bid > 0):
                return 0.0, 1.0, 0.0, 0.0, 0.0
            bb        = st.best_bid
            ba        = st.best_ask
            bid_depth = round(sum(st.bids.values()), 2)
            ask_depth = round(sum(st.asks.values()), 2)

        spread = round(ba - bb, 6)
        return bb, ba, spread, bid_depth, ask_depth

    def get_midpoint_trend(self, lookback_secs: float = 60.0) -> float:
        """
        Return the UP-token midpoint change over the last lookback_secs.

        Positive = midpoint rose (market pricing UP higher).
        Negative = midpoint fell (market pricing DOWN higher).
        Returns 0.0 if insufficient history — caller should pass through.

        Used to filter entries where CLOB trend opposes trade direction:
          - Skip UP  when trend < -0.10 (market trending down)
          - Skip DOWN when trend > +0.10 (market trending up)
        Cowork finding: strong upward trend → 29.4% WR; strong downward → 13.8% WR.
        """
        with self._lock:
            up_id = self._token_id_up
            st    = self._states.get(up_id)

        if not (up_id and st and len(st.midpoint_history) >= 2):
            return 0.0

        now    = time.time()
        cutoff = now - lookback_secs

        with self._lock:
            history = list(st.midpoint_history)  # snapshot to avoid lock hold

        in_window = [(ts, mid) for ts, mid in history if ts >= cutoff]
        if len(in_window) < 2:
            return 0.0

        return round(in_window[-1][1] - in_window[0][1], 6)

    def get_recent_trade_count(self, lookback_secs: float = 60.0) -> int:
        """
        Return the number of last_trade_price events on the UP token in the
        last lookback_secs. Used to detect crowded/active markets.

        Cowork finding (133 trades, Apr 10-13): ETH-15m with >5 trades in 60s
        has 28.6% WR vs 66.7% when ≤5 trades (p=0.037).
        Returns 0 if no history available.
        """
        with self._lock:
            up_id = self._token_id_up
            ts_list = list(self._trade_timestamps.get(up_id, []))

        cutoff = time.time() - lookback_secs
        return sum(1 for t in ts_list if t > cutoff)

    def get_prices(self) -> tuple[float, float, bool]:
        """
        Return (up_price, down_price, is_live).
        is_live=True means the prices came from the live WebSocket feed.
        Returns (0.5, 0.5, False) if the feed is not ready.
        """
        with self._lock:
            up_id     = self._token_id_up
            down_id   = self._token_id_down
            connected = self._connected
            up_st     = self._states.get(up_id)
            down_st   = self._states.get(down_id)

        if not (up_id and connected and up_st and up_st.last_updated > 0):
            return 0.5, 0.5, False

        up_mid = up_st.midpoint
        if up_mid <= 0:
            return 0.5, 0.5, False

        # If we have a fresh down-side midpoint, use it; otherwise derive from UP
        if down_st and down_st.last_updated > 0 and down_st.midpoint > 0:
            down_mid = down_st.midpoint
        else:
            down_mid = round(1.0 - up_mid, 6)

        return up_mid, down_mid, True

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # ── WebSocket internals ────────────────────────────────────────────────────

    def _send_subscribe(self, ws: websocket.WebSocketApp) -> None:
        with self._lock:
            ids = [x for x in [self._token_id_up, self._token_id_down] if x]
        if not ids:
            return
        msg = json.dumps({"assets_ids": ids, "type": "market"})
        ws.send(msg)
        print(f"[CLOB FEED] Subscribed to {len(ids)} token(s) — {ids[0][:20]}...")

    def _on_open(self, ws) -> None:
        with self._lock:
            self._connected = True
        print("[CLOB FEED] Connected")
        self._send_subscribe(ws)

    def _on_close(self, ws, code, msg) -> None:
        with self._lock:
            self._connected = False
        print("[CLOB FEED] Disconnected")

    def _on_error(self, ws, error) -> None:
        print(f"[CLOB FEED] Error: {error}")

    def _on_message(self, ws, raw: str) -> None:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for msg in data:
                    self._handle_event(msg)
            elif isinstance(data, dict):
                self._handle_event(data)
        except Exception as exc:
            print(f"[CLOB FEED] Parse error: {exc}")

    def _handle_event(self, msg: dict) -> None:
        event_type = msg.get("event_type", msg.get("type", ""))
        asset_id   = msg.get("asset_id", "")

        if not asset_id or not event_type:
            return

        with self._lock:
            if asset_id not in self._states:
                return  # not a token we subscribed to
            state        = self._states[asset_id]
            condition_id = self._condition_id
            slug         = self._slug
            window_end   = self._window_end_ts

        seconds_left = max(0.0, window_end - time.time()) if window_end > 0 else 0.0

        if event_type == "book":
            bids = msg.get("bids", [])
            asks = msg.get("asks", [])
            with self._lock:
                state.apply_book(bids, asks)
                mid = state.midpoint
                bb  = state.best_bid
                ba  = state.best_ask
            self._log(event_type, asset_id, condition_id, slug,
                      mid, "", 0.0, bb, ba, mid, seconds_left)

        elif event_type == "price_change":
            changes = msg.get("changes", [])
            with self._lock:
                state.apply_price_change(changes)
                mid = state.midpoint
                bb  = state.best_bid
                ba  = state.best_ask
            first = changes[0] if changes else {}
            self._log(event_type, asset_id, condition_id, slug,
                      float(first.get("price", mid)),
                      first.get("side", ""),
                      float(first.get("size", 0)),
                      bb, ba, mid, seconds_left)

        elif event_type == "last_trade_price":
            price = float(msg.get("price", 0))
            size  = float(msg.get("size", 0))
            side  = msg.get("side", "")
            now   = time.time()
            with self._lock:
                state.last_updated = now
                mid = state.midpoint
                bb  = state.best_bid
                ba  = state.best_ask
                # Track trade timestamps; prune entries older than 120s
                ts_list = self._trade_timestamps.setdefault(asset_id, [])
                ts_list.append(now)
                cutoff = now - 120
                self._trade_timestamps[asset_id] = [t for t in ts_list if t > cutoff]
            self._log(event_type, asset_id, condition_id, slug,
                      price, side, size, bb, ba, mid, seconds_left)

    def _log(
        self,
        event_type:  str,
        token_id:    str,
        condition_id: str,
        slug:        str,
        price:       float,
        side:        str,
        size:        float,
        best_bid:    float,
        best_ask:    float,
        midpoint:    float,
        seconds_left: float,
    ) -> None:
        CLOB_EVENTS.append({
            "ts":           round(time.time(), 4),
            "event_type":   event_type,
            "token_id":     token_id,
            "condition_id": condition_id,
            "slug":         slug,
            "price":        round(price,    6),
            "side":         side,
            "size":         round(size,     2),
            "best_bid":     round(best_bid, 6),
            "best_ask":     round(best_ask, 6),
            "midpoint":     round(midpoint, 6),
            "seconds_left": round(seconds_left, 1),
        })

    def _run_forever(self) -> None:
        while self._running:
            with self._lock:
                up_id = self._token_id_up
            if not up_id:
                time.sleep(1)
                continue
            try:
                self._ws = websocket.WebSocketApp(
                    CLOB_WS,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                print(f"[CLOB FEED] Connection error: {exc}")
            with self._lock:
                self._connected = False
            if self._running:
                print(f"[CLOB FEED] Reconnecting in {RECONNECT_DELAY}s...")
                time.sleep(RECONNECT_DELAY)
