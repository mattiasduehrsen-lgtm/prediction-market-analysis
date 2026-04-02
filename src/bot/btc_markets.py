"""
BTC strike market finder.

Fetches and caches the active "Bitcoin above ___ on [date]?" markets from Polymarket.
Each event contains ~11 markets at different strike prices (e.g. $64k, $66k, $68k...).
These resolve at noon ET daily based on Binance BTC/USDT 1-min candle close.

Cache refreshes every 10 minutes or when called with force=True.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

CACHE_PATH = Path("output/btc_trading/markets_cache.json")
CACHE_TTL  = 600  # 10 minutes


@dataclass
class StrikeMarket:
    condition_id: str
    question: str
    strike: int          # e.g. 66000
    yes_price: float     # current YES price (0-1)
    no_price: float      # 1 - yes_price
    liquidity: float
    end_date: str        # ISO string
    end_ts: float        # unix timestamp
    token_id_yes: str = ""
    token_id_no: str  = ""

    @property
    def seconds_to_expiry(self) -> float:
        return self.end_ts - time.time()

    @property
    def hours_to_expiry(self) -> float:
        return self.seconds_to_expiry / 3600

    def is_tradeable(self) -> bool:
        """Market is tradeable if it has liquidity and >30 min to expiry."""
        return self.liquidity > 100 and self.seconds_to_expiry > 1800


@dataclass
class BTCMarketSnapshot:
    fetched_at: float
    markets: list[StrikeMarket]
    event_title: str = ""
    event_end: str = ""

    def atm_markets(self, btc_price: float, n: int = 3) -> list[StrikeMarket]:
        """Return the n markets with strikes closest to current BTC price."""
        tradeable = [m for m in self.markets if m.is_tradeable()]
        return sorted(tradeable, key=lambda m: abs(m.strike - btc_price))[:n]

    def find_strike(self, strike: int) -> StrikeMarket | None:
        for m in self.markets:
            if m.strike == strike:
                return m
        return None


def _parse_strike(question: str) -> int | None:
    """Extract dollar strike from 'Will the price of Bitcoin be above $68,000 on ...'"""
    m = re.search(r"\$([0-9,]+)", question)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_end_ts(end_date: str) -> float:
    try:
        dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


def _fetch_btc_above_event() -> dict[str, Any] | None:
    """Find the most-current active 'Bitcoin above' event with order book enabled."""
    try:
        r = httpx.get(
            f"{GAMMA_API}/events",
            params={
                "limit": 50,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=15,
        )
        r.raise_for_status()
        events = r.json()
    except Exception as exc:
        print(f"[MARKETS] Failed to fetch events: {exc}")
        return None

    # Find active "Bitcoin above" events with order book
    candidates = [
        e for e in events
        if "bitcoin above" in e.get("title", "").lower()
        and e.get("enableOrderBook", False)
        and not e.get("closed", True)
        and e.get("active", False)
    ]
    if not candidates:
        return None

    # Sort by end date ascending — prefer soonest ending
    candidates.sort(key=lambda e: e.get("endDate", ""))

    # Pick the first event that still has markets with live prices (5-95% range).
    # The current-day event often has all markets resolved to 0 or 1 by midday.
    for event in candidates:
        for m in event.get("markets", []):
            prices_raw = m.get("outcomePrices", "[]")
            try:
                prices = [float(x) for x in (json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw)]
            except Exception:
                continue
            yes = prices[0] if prices else None
            if yes is not None and 0.05 < yes < 0.95:
                return event  # this event still has live markets

    # Fallback: return soonest ending regardless
    return candidates[0]


def _enrich_with_clob(markets: list[StrikeMarket]) -> None:
    """Fetch token IDs from CLOB for each market (needed for order placement)."""
    for m in markets:
        try:
            r = httpx.get(
                f"{CLOB_API}/markets/{m.condition_id}",
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                tokens = data.get("tokens", [])
                for t in tokens:
                    if t.get("outcome", "").lower() in ("yes", "up"):
                        m.token_id_yes = t.get("token_id", "")
                    elif t.get("outcome", "").lower() in ("no", "down"):
                        m.token_id_no = t.get("token_id", "")
        except Exception:
            pass


def fetch(force: bool = False) -> BTCMarketSnapshot | None:
    """
    Return a BTCMarketSnapshot with current strike markets.
    Uses cache unless stale or force=True.
    """
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Try cache first
    if not force and CACHE_PATH.exists():
        try:
            cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            age = time.time() - cached.get("fetched_at", 0)
            if age < CACHE_TTL:
                markets = [StrikeMarket(**m) for m in cached["markets"]]
                snap = BTCMarketSnapshot(
                    fetched_at=cached["fetched_at"],
                    markets=markets,
                    event_title=cached.get("event_title", ""),
                    event_end=cached.get("event_end", ""),
                )
                return snap
        except Exception:
            pass

    # Fetch fresh
    event = _fetch_btc_above_event()
    if not event:
        print("[MARKETS] No active Bitcoin above event found")
        return None

    markets: list[StrikeMarket] = []
    for raw_market in event.get("markets", []):
        strike = _parse_strike(raw_market.get("question", ""))
        if strike is None:
            continue

        prices_raw = raw_market.get("outcomePrices", "[]")
        try:
            prices = [float(x) for x in (json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw)]
        except Exception:
            prices = []

        yes_price = prices[0] if len(prices) > 0 else 0.5
        no_price  = prices[1] if len(prices) > 1 else 1 - yes_price

        end_date = raw_market.get("endDate", event.get("endDate", ""))
        markets.append(StrikeMarket(
            condition_id=raw_market.get("conditionId", ""),
            question=raw_market.get("question", ""),
            strike=strike,
            yes_price=yes_price,
            no_price=no_price,
            liquidity=float(raw_market.get("liquidity") or 0),
            end_date=end_date,
            end_ts=_parse_end_ts(end_date),
        ))

    markets.sort(key=lambda m: m.strike)

    # Enrich with CLOB token IDs
    _enrich_with_clob(markets)

    snap = BTCMarketSnapshot(
        fetched_at=time.time(),
        markets=markets,
        event_title=event.get("title", ""),
        event_end=event.get("endDate", ""),
    )

    # Save cache
    try:
        CACHE_PATH.write_text(
            json.dumps({
                "fetched_at": snap.fetched_at,
                "event_title": snap.event_title,
                "event_end": snap.event_end,
                "markets": [m.__dict__ for m in markets],
            }, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[MARKETS] Cache write failed: {exc}")

    n = len(markets)
    print(f"[MARKETS] Loaded {n} strike markets for '{snap.event_title}' (expires {snap.event_end[:10]})")
    return snap
