from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.indexers.kalshi.client import KalshiClient
from src.indexers.polymarket.client import PolymarketClient

CURRENT_DATA_DIR = Path("data/current")
KALSHI_DIR = CURRENT_DATA_DIR / "kalshi"
POLYMARKET_DIR = CURRENT_DATA_DIR / "polymarket"


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _records(items: list[Any], fetched_at: datetime) -> list[dict[str, Any]]:
    records = []
    for item in items:
        if is_dataclass(item):
            record = asdict(item)
        elif isinstance(item, dict):
            record = dict(item)
        else:
            record = vars(item)

        record["_fetched_at"] = fetched_at
        records.append(record)
    return records


def _write_snapshot(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_parquet(path, index=False)


def _collect_kalshi_markets(client: KalshiClient, min_close_ts: int, max_close_ts: int) -> list[Any]:
    markets = []
    cursor = None

    while True:
        batch, cursor = next(
            client.iter_markets(
                limit=1000,
                cursor=cursor,
                min_close_ts=min_close_ts,
                max_close_ts=max_close_ts,
            )
        )
        if batch:
            markets.extend(batch)
        if not cursor:
            break

    return markets


def collect_current_data() -> None:
    """Fetch bounded, recent market snapshots without historical backfills."""
    now = datetime.now(timezone.utc)
    fetched_at = datetime.utcnow()

    kalshi_market_hours = _env_int("CURRENT_KALSHI_MARKET_HOURS", 48)
    kalshi_recent_trades_limit = _env_int("CURRENT_KALSHI_RECENT_TRADES_LIMIT", 1000)
    polymarket_markets_limit = _env_int("CURRENT_POLYMARKET_MARKETS_LIMIT", 500)
    polymarket_trades_limit = _env_int("CURRENT_POLYMARKET_TRADES_LIMIT", 500)

    min_close_ts = int(now.timestamp() * 1000)
    max_close_ts = int((now + timedelta(hours=kalshi_market_hours)).timestamp() * 1000)

    print("Collecting lightweight current snapshots...")
    print(f"Kalshi markets: closes within next {kalshi_market_hours}h")
    print(f"Kalshi recent trades limit: {kalshi_recent_trades_limit}")
    print(f"Polymarket markets limit: {polymarket_markets_limit}")
    print(f"Polymarket trades limit: {polymarket_trades_limit}")

    with KalshiClient() as kalshi_client:
        kalshi_markets = _collect_kalshi_markets(kalshi_client, min_close_ts, max_close_ts)
        kalshi_recent_trades = kalshi_client.get_recent_trades(limit=kalshi_recent_trades_limit)

    with PolymarketClient() as polymarket_client:
        polymarket_markets = polymarket_client.get_markets(limit=polymarket_markets_limit, closed=False)
        polymarket_recent_trades = polymarket_client.get_trades(limit=polymarket_trades_limit)

    _write_snapshot(KALSHI_DIR / "markets.parquet", _records(kalshi_markets, fetched_at))
    _write_snapshot(KALSHI_DIR / "trades.parquet", _records(kalshi_recent_trades, fetched_at))
    _write_snapshot(POLYMARKET_DIR / "markets.parquet", _records(polymarket_markets, fetched_at))
    _write_snapshot(POLYMARKET_DIR / "trades.parquet", _records(polymarket_recent_trades, fetched_at))

    print(f"Saved Kalshi markets snapshot: {len(kalshi_markets)} rows")
    print(f"Saved Kalshi trades snapshot: {len(kalshi_recent_trades)} rows")
    print(f"Saved Polymarket markets snapshot: {len(polymarket_markets)} rows")
    print(f"Saved Polymarket trades snapshot: {len(polymarket_recent_trades)} rows")
