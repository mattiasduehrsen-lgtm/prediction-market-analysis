from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from src.indexers.kalshi.client import KalshiClient
from src.indexers.polymarket.client import PolymarketClient

CURRENT_DATA_DIR = Path("data/current")
HISTORICAL_DATA_DIR = Path("data/historical")
KALSHI_DIR = CURRENT_DATA_DIR / "kalshi"
POLYMARKET_DIR = CURRENT_DATA_DIR / "polymarket"
CLOB_API_URL = "https://clob.polymarket.com"


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
    """Fetch active Kalshi binary markets via the /events endpoint.

    The /markets endpoint is overwhelmed by pre-created KXMVE exotic sports and weather
    markets (all 'initialized', no prices).  /events?with_nested_markets=true returns
    only real, live prediction markets with actual bid/ask prices.
    We still apply the close-time filter in post so we only keep markets that resolve
    within the same window we care about.
    """
    markets = []
    for batch, cursor in client.iter_markets_via_events(limit=200, max_markets=5000):
        for m in batch:
            # Keep markets that close within our desired window (or have no close time).
            close_time = getattr(m, "close_time", None)
            if close_time is not None:
                try:
                    close_ts_ms = int(close_time.timestamp() * 1000)
                    if close_ts_ms < min_close_ts or close_ts_ms > max_close_ts:
                        continue
                except Exception:
                    pass
            markets.append(m)
        if not cursor:
            break
    return markets


def _fetch_clob_price_history(markets: list[Any], lookback_seconds: int = 3600) -> list[dict[str, Any]]:
    """Fetch per-market price history from the CLOB API for the top markets by liquidity.

    Returns synthetic trade records compatible with the Trade dataclass schema so
    they can be merged with Data API trades and feed the VWAP momentum strategy.
    """
    now = int(time.time())
    start_ts = now - lookback_seconds

    # Build token_id -> (condition_id, outcome_name, outcome_index) mapping
    # for the top 100 markets by liquidity
    sorted_markets = sorted(markets, key=lambda m: float(getattr(m, "liquidity", 0) or 0), reverse=True)[:100]

    token_map: dict[str, tuple[str, str, int]] = {}
    for market in sorted_markets:
        condition_id = str(getattr(market, "condition_id", "") or "")
        try:
            outcomes = json.loads(str(getattr(market, "outcomes", "[]") or "[]"))
            token_ids = json.loads(str(getattr(market, "clob_token_ids", "[]") or "[]"))
        except Exception:
            continue
        for idx, (outcome, token_id) in enumerate(zip(outcomes, token_ids)):
            if token_id:
                token_map[str(token_id)] = (condition_id, str(outcome), idx)

    if not token_map:
        return []

    synthetic_trades: list[dict[str, Any]] = []
    fetched = 0
    errors = 0

    with httpx.Client(timeout=15.0) as client:
        for token_id, (condition_id, outcome, outcome_index) in token_map.items():
            try:
                resp = client.get(
                    f"{CLOB_API_URL}/prices-history",
                    params={"market": token_id, "startTs": start_ts, "endTs": now, "fidelity": 1},
                )
                if resp.status_code != 200:
                    errors += 1
                    continue
                history = resp.json().get("history", [])
                for point in history:
                    t = point.get("t", 0)
                    p = point.get("p")
                    if not t or p is None:
                        continue
                    try:
                        price = float(p)
                    except (TypeError, ValueError):
                        continue
                    if price <= 0 or price >= 1:
                        continue
                    synthetic_trades.append(
                        {
                            "condition_id": condition_id,
                            "asset": token_id,
                            "side": "BUY",
                            "size": 100.0,
                            "price": price,
                            "timestamp": int(t),
                            "outcome": outcome,
                            "outcome_index": outcome_index,
                            "transaction_hash": f"clob_{token_id}_{t}",
                        }
                    )
                fetched += 1
            except Exception:
                errors += 1
                continue

    print(f"CLOB price history: {fetched} tokens fetched, {len(synthetic_trades)} data points, {errors} errors")
    return synthetic_trades


def _fetch_order_book_signals(markets: list[Any]) -> list[dict[str, Any]]:
    """Fetch order book for the top markets and compute imbalance signals.

    Order book imbalance = (total bid size - total ask size) / (total bid size + total ask size)
    Range: -1.0 (all sellers) to +1.0 (all buyers). Positive = buying pressure.
    """
    try:
        import pmxt  # requires Node.js + `npm install -g pmxtjs`
    except Exception as exc:
        print(f"Order book signals skipped: pmxt unavailable ({exc})")
        return []

    sorted_markets = sorted(markets, key=lambda m: float(getattr(m, "liquidity", 0) or 0), reverse=True)[:50]

    records: list[dict[str, Any]] = []
    try:
        pm = pmxt.Polymarket()
    except Exception as exc:
        print(f"Order book signals skipped: pmxtjs server failed to start ({exc})")
        return []
    fetched = 0
    errors = 0

    for market in sorted_markets:
        condition_id = str(getattr(market, "condition_id", "") or "")
        try:
            token_ids = json.loads(str(getattr(market, "clob_token_ids", "[]") or "[]"))
            outcomes = json.loads(str(getattr(market, "outcomes", "[]") or "[]"))
        except Exception:
            continue

        for idx, (token_id, outcome) in enumerate(zip(token_ids, outcomes)):
            if not token_id:
                continue
            try:
                ob = pm.fetch_order_book(str(token_id))
                bid_size = sum(level.size for level in ob.bids)
                ask_size = sum(level.size for level in ob.asks)
                total = bid_size + ask_size
                imbalance = (bid_size - ask_size) / total if total > 0 else 0.0
                best_bid = ob.bids[0].price if ob.bids else None
                best_ask = ob.asks[0].price if ob.asks else None
                spread = (best_ask - best_bid) if (best_bid and best_ask) else None
                records.append({
                    "condition_id": condition_id,
                    "outcome": str(outcome),
                    "outcome_index": idx,
                    "token_id": str(token_id),
                    "bid_size": round(bid_size, 2),
                    "ask_size": round(ask_size, 2),
                    "ob_imbalance": round(imbalance, 4),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread": round(spread, 4) if spread is not None else None,
                })
                fetched += 1
            except Exception:
                errors += 1
                continue

    print(f"Order book signals: {fetched} tokens fetched, {errors} errors")
    return records


def collect_current_data() -> None:
    """Fetch bounded, recent market snapshots without historical backfills."""
    now = datetime.now(timezone.utc)
    fetched_at = datetime.utcnow()

    kalshi_market_hours = _env_int("CURRENT_KALSHI_MARKET_HOURS", 17520)  # 2 years — fetch all active markets
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
        # Paginate markets to get up to the configured limit (default 1000).
        polymarket_markets = []
        market_offset = 0
        market_page = 500
        while len(polymarket_markets) < polymarket_markets_limit:
            batch = polymarket_client.get_markets(limit=min(market_page, polymarket_markets_limit - len(polymarket_markets)), offset=market_offset, closed=False)
            if not batch:
                break
            polymarket_markets.extend(batch)
            if len(batch) < market_page:
                break
            market_offset += len(batch)

        # Paginate trades until we have at least 30 minutes of history.
        # Stops early if the API rejects the offset (it caps around 3000).
        cutoff_ts = time.time() - 1800  # 30 minutes ago
        polymarket_recent_trades = []
        offset = 0
        max_per_page = 500
        while len(polymarket_recent_trades) < polymarket_trades_limit:
            try:
                batch = polymarket_client.get_trades(limit=max_per_page, offset=offset)
            except Exception:
                break
            if not batch:
                break
            polymarket_recent_trades.extend(batch)
            oldest_ts = min(
                (t.timestamp if hasattr(t, "timestamp") else t.get("timestamp", float("inf")))
                for t in batch
            )
            if oldest_ts < cutoff_ts:
                break
            if len(batch) < max_per_page:
                break
            offset += len(batch)

    # Fetch order book depth for top markets via pmxt (requires Node.js + pmxtjs).
    # Fails gracefully if pmxtjs is not installed — bot continues without order book data.
    print("Fetching order book signals for top markets...")
    try:
        ob_signals = _fetch_order_book_signals(polymarket_markets)
    except Exception as exc:
        print(f"Order book signals skipped: {exc}")
        ob_signals = []
    if ob_signals:
        _write_snapshot(POLYMARKET_DIR / "order_books.parquet", ob_signals)
        print(f"Saved order book signals: {len(ob_signals)} rows")

    # Fetch 6 hours of per-market price history from the CLOB API.
    # The Data API only has ~8 min of global trades which makes VWAP ≈ current price.
    # CLOB history gives per-token time-series so the strategy has real price trends.
    clob_lookback = _env_int("CURRENT_CLOB_LOOKBACK_SECONDS", 21600)  # 6 hours
    print(f"Fetching CLOB price history for top markets (lookback={clob_lookback}s)...")
    clob_history = _fetch_clob_price_history(polymarket_markets, lookback_seconds=clob_lookback)

    # Merge Data API trades + CLOB synthetic trades into one file.
    # Add _fetched_at to CLOB records so the schema matches.
    for rec in clob_history:
        rec["_fetched_at"] = fetched_at
    data_api_records = _records(polymarket_recent_trades, fetched_at)
    all_trade_records = data_api_records + clob_history

    _write_snapshot(KALSHI_DIR / "markets.parquet", _records(kalshi_markets, fetched_at))
    _write_snapshot(KALSHI_DIR / "trades.parquet", _records(kalshi_recent_trades, fetched_at))
    _write_snapshot(POLYMARKET_DIR / "markets.parquet", _records(polymarket_markets, fetched_at))
    _write_snapshot(POLYMARKET_DIR / "trades.parquet", all_trade_records)

    # Archive a timestamped copy for historical analysis and backtesting.
    ts = now.strftime("%Y-%m-%dT%H-%M-%S")
    _write_snapshot(HISTORICAL_DATA_DIR / "polymarket" / f"trades_{ts}.parquet", all_trade_records)
    _write_snapshot(HISTORICAL_DATA_DIR / "polymarket" / f"markets_{ts}.parquet", _records(polymarket_markets, fetched_at))
    _write_snapshot(HISTORICAL_DATA_DIR / "kalshi" / f"trades_{ts}.parquet", _records(kalshi_recent_trades, fetched_at))
    _write_snapshot(HISTORICAL_DATA_DIR / "kalshi" / f"markets_{ts}.parquet", _records(kalshi_markets, fetched_at))

    print(f"Saved Kalshi markets snapshot: {len(kalshi_markets)} rows")
    print(f"Saved Kalshi trades snapshot: {len(kalshi_recent_trades)} rows")
    print(f"Saved Polymarket markets snapshot: {len(polymarket_markets)} rows")
    print(f"Saved Polymarket trades snapshot: {len(all_trade_records)} rows ({len(data_api_records)} live + {len(clob_history)} CLOB history)")
    print(f"Archived historical snapshot: {ts}")
