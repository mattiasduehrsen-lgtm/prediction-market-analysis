"""
Polymarket 5-minute Up/Down market fetcher.

Each 5-minute window has a predictable slug:
  {asset}-updown-5m-{unix_timestamp_of_window_end}

Window ends are at exact multiples of 300 seconds (Unix epoch).

Supports: BTC, ETH, SOL, XRP (just change the asset slug prefix).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import httpx

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

# Slug prefixes per asset — extend as needed
SLUG_PREFIXES: dict[str, str] = {
    "BTC": "btc-updown-5m",
    "ETH": "eth-updown-5m",
    "SOL": "sol-updown-5m",
    "XRP": "xrp-updown-5m",
}

# Entry/exit thresholds
ENTRY_MAX        = 0.05   # buy UP/DOWN when priced at or below this
TAKE_PROFIT      = 0.30   # exit when our side hits 30¢ (6x from 5¢ entry)
FORCE_EXIT_PRICE = 0.85   # unconditional exit if our side reaches 85¢ — never give back big wins
# NO stop loss — binary markets need room; cutting on noise locks losses before reversals
MIN_SECONDS = 90          # don't enter with less than this many seconds remaining
FORCE_EXIT  = 60          # force-close by time when this many seconds remain
TAKER_FEE   = 0.10        # 10% taker fee — simulated in paper trading


@dataclass
class Market5m:
    slug: str
    condition_id: str
    asset: str
    up_price: float       # current probability UP wins (0–1)
    down_price: float     # current probability DOWN wins (0–1), ≈ 1 - up_price
    window_end_ts: float  # unix timestamp when this window closes
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


def fetch_live_prices(market: "Market5m") -> tuple[float, float, bool]:
    """
    Fetch real-time UP/DOWN prices from the CLOB midpoint API.

    Returns (up_price, down_price, clob_ok) where clob_ok=True means a fresh
    CLOB price was returned. clob_ok=False means the call failed and last known
    prices were returned as a fallback.

    The Gamma API's outcomePrices field is stale — it does not update mid-window.
    The CLOB midpoint reflects the current best-bid/best-ask and moves in real time.
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
    except Exception as exc:
        return market.up_price, market.down_price, False


def get_window_end() -> int:
    """Return the Unix timestamp of the end of the current 5-minute window."""
    now = int(time.time())
    return (now // 300 + 1) * 300


def fetch_market(asset: str = "BTC") -> Optional[Market5m]:
    """
    Fetch the current active 5-minute market for the given asset.
    Tries current window, then ±1 window in case we're at a boundary.
    """
    prefix = SLUG_PREFIXES.get(asset.upper(), f"{asset.lower()}-updown-5m")

    # Try current window first, then adjacent windows
    for offset in (0, -1, 1):
        window_end = get_window_end() + offset * 300
        market = _fetch_slug(slug=f"{prefix}-{window_end}", asset=asset, window_end=window_end)
        if market and not market.is_expired():
            return market

    return None


def _fetch_slug(slug: str, asset: str, window_end: int) -> Optional[Market5m]:
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
        print(f"[5M] Fetch error for {slug}: {exc}")
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

    # Parse outcome prices
    prices_raw = m.get("outcomePrices", "[0.5,0.5]")
    try:
        prices = [float(x) for x in (json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw)]
    except Exception:
        prices = [0.5, 0.5]

    # Parse outcome labels (should be ["Up","Down"])
    outcomes_raw = m.get("outcomes", '["Up","Down"]')
    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
    except Exception:
        outcomes = ["Up", "Down"]

    up_price   = 0.5
    down_price = 0.5
    token_id_up   = ""
    token_id_down = ""

    for i, label in enumerate(outcomes):
        price = prices[i] if i < len(prices) else 0.5
        if label.lower() == "up":
            up_price = price
        elif label.lower() == "down":
            down_price = price

    # Parse CLOB token IDs (needed for live order placement later)
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
        up_price=up_price,
        down_price=down_price,
        window_end_ts=float(window_end),
        liquidity=liquidity,
        token_id_up=token_id_up,
        token_id_down=token_id_down,
    )
