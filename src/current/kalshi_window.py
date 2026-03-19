from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.indexers.kalshi.client import KalshiClient

DEFAULT_HOURS = 48
DEFAULT_MAX_WORKERS = 10
WINDOW_DATA_DIR = Path("data/current/kalshi_last_48h")


def _records(items: list[Any], fetched_at: datetime) -> list[dict[str, Any]]:
    return [{**asdict(item), "_fetched_at": fetched_at} for item in items]


def collect_kalshi_window(
    hours: int = DEFAULT_HOURS,
    output_dir: Path = WINDOW_DATA_DIR,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> tuple[Path, Path]:
    now = datetime.now(timezone.utc)
    fetched_at = datetime.utcnow()
    start = now - timedelta(hours=hours)
    min_ts = int(start.timestamp() * 1000)
    max_ts = int(now.timestamp() * 1000)

    output_dir.mkdir(parents=True, exist_ok=True)

    print(
        "Collecting Kalshi window",
        f"from {start.isoformat()} to {now.isoformat()}",
    )

    with KalshiClient() as client:
        trades = client.get_trades(limit=1000, verbose=True, min_ts=min_ts, max_ts=max_ts)

    tickers = sorted({trade.ticker for trade in trades})
    print(f"Fetched {len(trades)} trades across {len(tickers)} markets")

    markets = []

    def fetch_market(ticker: str):
        with KalshiClient() as client:
            return client.get_market(ticker)

    if tickers:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_market, ticker): ticker for ticker in tickers}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    markets.append(future.result())
                except Exception as exc:
                    print(f"Failed to fetch market {ticker}: {exc}")

    trades_path = output_dir / "trades.parquet"
    markets_path = output_dir / "markets.parquet"
    window_path = output_dir / "window.json"

    pd.DataFrame(_records(trades, fetched_at)).to_parquet(trades_path, index=False)
    pd.DataFrame(_records(markets, fetched_at)).to_parquet(markets_path, index=False)
    window_path.write_text(
        (
            "{\n"
            f'  "start": "{start.isoformat()}",\n'
            f'  "end": "{now.isoformat()}",\n'
            f'  "hours": {hours},\n'
            f'  "trades": {len(trades)},\n'
            f'  "markets": {len(markets)}\n'
            "}\n"
        )
    )

    print(f"Saved trades to {trades_path}")
    print(f"Saved markets to {markets_path}")
    print(f"Saved metadata to {window_path}")

    return trades_path, markets_path
