"""
Polymarket Up/Down market fetcher — supports 5m and 15m windows.

Slug format:
  {asset}-updown-5m-{window_start_ts}   (e.g. btc-updown-5m-1775219400)
  {asset}-updown-15m-{window_start_ts}  (e.g. sol-updown-15m-1775219400)

Window ends = window_start + window_seconds.
Window starts are at multiples of window_seconds (Unix epoch).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import httpx

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

# Supported window sizes in seconds
WINDOW_SECONDS: dict[str, int] = {
    "5m":  300,
    "15m": 900,
}

# Slug prefixes keyed by (window, asset)
SLUG_PREFIXES: dict[str, dict[str, str]] = {
    "5m": {
        "BTC": "btc-updown-5m",
        "ETH": "eth-updown-5m",
        "SOL": "sol-updown-5m",
        "XRP": "xrp-updown-5m",
    },
    "15m": {
        "BTC": "btc-updown-15m",
        "ETH": "eth-updown-15m",
        "SOL": "sol-updown-15m",
        "XRP": "xrp-updown-15m",
    },
}

# ── Mean-reversion strategy constants (5m) ────────────────────────────────────
ENTRY_MIN        = 0.28   # lowered 0.33→0.28: 59% of windows had price below 0.33 (all missed)
ENTRY_MAX        = 0.39   # raised from 0.40: 0.39-0.40 entries had lowest EV
TAKE_PROFIT      = 0.92   # hold for full reversal — settlement pays $1.00
MIN_SECONDS      = 240    # enter in first 60s of 5m window (300 - 60 = 240s remaining)
FORCE_EXIT       = 5      # close at 5s remaining — avoid settlement chaos
SOFT_EXIT_SECS   = 115    # soft exit: bail on stalled reversions with ~2min left
SOFT_EXIT_PRICE  = 0.25   # exit at 115s if price ≤ 0.25
BTC_SKIP_RATE    = 20.0   # $/min BTC move against your side → skip entry
BTC_MAGNITUDE_MAX = 0.05  # max Chainlink % move from window start to allow entry

# ── Momentum strategy constants ───────────────────────────────────────────────
MOMENTUM_ENTRY_WINDOW = 30   # seconds — enter within first 30s of window only
MOMENTUM_MIN_PREV_MOVE = 0.15  # min |cross_window_pct| to enter (PolyBackTest threshold)


@dataclass
class Market5m:
    slug: str
    condition_id: str
    asset: str
    window: str        # "5m" or "15m"
    up_price: float
    down_price: float
    window_end_ts: float
    liquidity: float
    token_id_up: str = ""
    token_id_down: str = ""

    @property
    def seconds_remaining(self) -> float:
        return max(0.0, self.window_end_ts - time.time())

    @property
    def minutes_remaining(self) -> float:
        return self.seconds_remaining / 60

    def is_expired(self) -> bool:
        return self.seconds_remaining <= 0

    @property
    def window_seconds(self) -> int:
        return WINDOW_SECONDS.get(self.window, 300)


def fetch_live_prices(market: "Market5m") -> tuple[float, float, bool]:
    """
    Fetch real-time UP/DOWN prices from the CLOB midpoint API.
    Returns (up_price, down_price, clob_ok).
    """
    if not market.token_id_up:
        return market.up_price, market.down_price, False
    try:
        r = httpx.get(
            f"{CLOB_API}/midpoint",
            params={"token_id": market.token_id_up},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        up = float(data.get("mid", market.up_price))
        return up, round(1.0 - up, 6), True
    except Exception:
        return market.up_price, market.down_price, False


def get_window_start(window: str = "5m") -> int:
    """Return the Unix timestamp of the START of the current window."""
    ws = WINDOW_SECONDS.get(window, 300)
    now = int(time.time())
    return (now // ws) * ws


def fetch_market(asset: str = "BTC", window: str = "5m") -> Optional[Market5m]:
    """
    Fetch the current active market for the given asset and window size.
    Tries current window, then ±1 window in case we're at a boundary.
    """
    ws = WINDOW_SECONDS.get(window, 300)
    prefix = SLUG_PREFIXES.get(window, {}).get(
        asset.upper(), f"{asset.lower()}-updown-{window}"
    )

    for offset in (0, 1, -1):
        window_start = get_window_start(window) + offset * ws
        window_end   = window_start + ws
        market = _fetch_slug(
            slug=f"{prefix}-{window_start}",
            asset=asset,
            window=window,
            window_end=window_end,
        )
        if market and not market.is_expired():
            return market

    return None


def _fetch_slug(slug: str, asset: str, window: str, window_end: int) -> Optional[Market5m]:
    """Fetch a specific market by slug and parse its prices."""
    try:
        r = httpx.get(
            f"{GAMMA_API}/events",
            params={"slug": slug, "limit": 1},
            timeout=10,
        )
        r.raise_for_status()
        events = r.json()
    except Exception as exc:
        print(f"[MARKET] Fetch error for {slug}: {exc}")
        return None

    if not events:
        return None

    event = events[0]
    markets = event.get("markets", [])
    if not markets:
        return None

    m = markets[0]
    condition_id = m.get("conditionId", "")
    if not condition_id:
        return None

    liquidity = float(m.get("liquidity") or 0)

    prices_raw = m.get("outcomePrices", "[0.5,0.5]")
    try:
        prices = [float(x) for x in (json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw)]
    except Exception:
        prices = [0.5, 0.5]

    outcomes_raw = m.get("outcomes", '["Up","Down"]')
    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
    except Exception:
        outcomes = ["Up", "Down"]

    up_price = down_price = 0.5
    token_id_up = token_id_down = ""

    for i, label in enumerate(outcomes):
        price = prices[i] if i < len(prices) else 0.5
        if label.lower() == "up":
            up_price = price
        elif label.lower() == "down":
            down_price = price

    clob_raw = m.get("clobTokenIds", "[]")
    try:
        token_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
        for i, label in enumerate(outcomes):
            if i < len(token_ids):
                if label.lower() == "up":
                    token_id_up = str(token_ids[i])
                elif label.lower() == "down":
                    token_id_down = str(token_ids[i])
    except Exception:
        pass

    return Market5m(
        slug=slug,
        condition_id=condition_id,
        asset=asset,
        window=window,
        up_price=up_price,
        down_price=down_price,
        window_end_ts=float(window_end),
        liquidity=liquidity,
        token_id_up=token_id_up,
        token_id_down=token_id_down,
    )
