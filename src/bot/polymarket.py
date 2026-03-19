from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.indexers.polymarket.client import PolymarketClient


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _load_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".csv":
        return pd.read_csv(path)
    return pd.read_parquet(path)


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


def _select_existing(base_dir: Path, stem: str) -> Path:
    csv_path = base_dir / f"{stem}.csv"
    parquet_path = base_dir / f"{stem}.parquet"
    if csv_path.exists():
        return csv_path
    if parquet_path.exists():
        return parquet_path
    raise FileNotFoundError(f"Missing {stem}.csv or {stem}.parquet in {base_dir}")


@dataclass
class StrategyConfig:
    edge_threshold: float = 0.03
    min_recent_trades: int = 2
    min_recent_notional: float = 25.0
    min_liquidity: float = 1000.0
    min_buy_share: float = 0.55
    min_market_price: float = 0.10
    max_market_price: float = 0.90
    lookback_seconds: int = 3600
    max_candidates: int = 5
    exit_edge_threshold: float = -0.01
    take_profit_pct: float = 0.25
    stop_loss_pct: float = 0.20

    @classmethod
    def from_env(cls) -> StrategyConfig:
        return cls(
            edge_threshold=_env_float("PAPER_EDGE_THRESHOLD", 0.03),
            min_recent_trades=_env_int("PAPER_MIN_RECENT_TRADES", 2),
            min_recent_notional=_env_float("PAPER_MIN_RECENT_NOTIONAL", 25.0),
            min_liquidity=_env_float("PAPER_MIN_LIQUIDITY", 1000.0),
            min_buy_share=_env_float("PAPER_MIN_BUY_SHARE", 0.55),
            min_market_price=_env_float("PAPER_MIN_MARKET_PRICE", 0.10),
            max_market_price=_env_float("PAPER_MAX_MARKET_PRICE", 0.90),
            lookback_seconds=_env_int("PAPER_LOOKBACK_SECONDS", 3600),
            max_candidates=_env_int("PAPER_MAX_CANDIDATES", 5),
            exit_edge_threshold=_env_float("PAPER_EXIT_EDGE_THRESHOLD", -0.01),
            take_profit_pct=_env_float("PAPER_TAKE_PROFIT_PCT", 0.25),
            stop_loss_pct=_env_float("PAPER_STOP_LOSS_PCT", 0.20),
        )


@dataclass
class PortfolioConfig:
    starting_cash: float = 1000.0
    max_position_dollars: float = 100.0
    max_positions: int = 5

    @classmethod
    def from_env(cls) -> PortfolioConfig:
        return cls(
            starting_cash=_env_float("PAPER_STARTING_CASH", 1000.0),
            max_position_dollars=_env_float("PAPER_MAX_POSITION_DOLLARS", 100.0),
            max_positions=_env_int("PAPER_MAX_POSITIONS", 5),
        )


@dataclass
class Order:
    condition_id: str
    question: str
    outcome: str
    outcome_index: int
    side: str
    price: float
    size: float
    notional: float
    edge: float
    score: float
    reason: str = ""
    run_at: str = ""


class PolymarketSnapshot:
    def __init__(self, data_dir: Path | str = "data/current/polymarket"):
        self.data_dir = Path(data_dir)

    def ensure_snapshot(self) -> None:
        try:
            _select_existing(self.data_dir, "markets")
            _select_existing(self.data_dir, "trades")
            return
        except FileNotFoundError:
            pass

        fetched_at = datetime.utcnow()
        markets_limit = _env_int("CURRENT_POLYMARKET_MARKETS_LIMIT", 500)
        trades_limit = _env_int("CURRENT_POLYMARKET_TRADES_LIMIT", 500)

        print("Polymarket snapshot missing, fetching current data first...")
        with PolymarketClient() as client:
            markets = client.get_markets(limit=markets_limit, closed=False)
            trades = client.get_trades(limit=trades_limit)

        _write_snapshot(self.data_dir / "markets.parquet", _records(markets, fetched_at))
        _write_snapshot(self.data_dir / "trades.parquet", _records(trades, fetched_at))
        print(f"Saved Polymarket markets snapshot: {len(markets)} rows")
        print(f"Saved Polymarket trades snapshot: {len(trades)} rows")

    def load(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        self.ensure_snapshot()
        markets = _load_table(_select_existing(self.data_dir, "markets"))
        trades = _load_table(_select_existing(self.data_dir, "trades"))
        return markets, trades

    def outcome_frame(self) -> pd.DataFrame:
        markets, trades = self.load()

        market_rows = []
        for _, row in markets.iterrows():
            outcomes = json.loads(row["outcomes"]) if pd.notna(row["outcomes"]) else []
            prices = json.loads(row["outcome_prices"]) if pd.notna(row["outcome_prices"]) else []
            token_ids = json.loads(row["clob_token_ids"]) if pd.notna(row["clob_token_ids"]) else []

            for idx, outcome in enumerate(outcomes):
                price = float(prices[idx]) if idx < len(prices) else math.nan
                asset = str(token_ids[idx]) if idx < len(token_ids) else ""
                market_rows.append(
                    {
                        "market_id": row.get("id", ""),
                        "condition_id": row.get("condition_id", ""),
                        "question": row.get("question", ""),
                        "outcome": outcome,
                        "outcome_index": idx,
                        "asset": asset,
                        "market_price": price,
                        "volume": float(row.get("volume", 0) or 0),
                        "liquidity": float(row.get("liquidity", 0) or 0),
                        "active": bool(row.get("active", False)),
                        "closed": bool(row.get("closed", False)),
                        "end_date": row.get("end_date"),
                    }
                )

        outcomes_df = pd.DataFrame(market_rows)
        if outcomes_df.empty:
            return outcomes_df

        trades = trades.copy()
        trades["timestamp"] = pd.to_datetime(trades["timestamp"], unit="s", utc=True)
        latest_ts = trades["timestamp"].max()
        lookback_seconds = StrategyConfig.from_env().lookback_seconds
        cutoff = latest_ts - pd.Timedelta(seconds=lookback_seconds)
        recent = trades[trades["timestamp"] >= cutoff].copy()

        if recent.empty:
            recent_agg = pd.DataFrame(
                columns=[
                    "condition_id",
                    "outcome",
                    "outcome_index",
                    "recent_trade_count",
                    "recent_volume_shares",
                    "recent_notional",
                    "recent_vwap",
                    "buy_share",
                    "last_trade_price",
                    "last_trade_at",
                ]
            )
        else:
            recent["notional"] = recent["size"] * recent["price"]
            recent["buy_flag"] = (recent["side"].str.upper() == "BUY").astype(float)

            grouped = recent.groupby(["condition_id", "outcome", "outcome_index"], dropna=False)
            recent_agg = grouped.agg(
                recent_trade_count=("transaction_hash", "count"),
                recent_volume_shares=("size", "sum"),
                recent_notional=("notional", "sum"),
                weighted_notional=("notional", "sum"),
                weighted_price=("price", lambda s: (s * recent.loc[s.index, "size"]).sum()),
                buy_share=("buy_flag", "mean"),
                last_trade_price=("price", "last"),
                last_trade_at=("timestamp", "max"),
            ).reset_index()
            recent_agg["recent_vwap"] = recent_agg["weighted_price"] / recent_agg["recent_volume_shares"].clip(
                lower=1e-9
            )
            recent_agg = recent_agg.drop(columns=["weighted_notional", "weighted_price"])

        merged = outcomes_df.merge(
            recent_agg,
            on=["condition_id", "outcome", "outcome_index"],
            how="left",
        )

        for col in ["recent_trade_count", "recent_volume_shares", "recent_notional", "buy_share"]:
            merged[col] = merged[col].fillna(0)

        merged["recent_vwap"] = merged["recent_vwap"].fillna(merged["market_price"])
        merged["last_trade_price"] = merged["last_trade_price"].fillna(merged["market_price"])
        merged["edge"] = merged["recent_vwap"] - merged["market_price"]
        merged["score"] = (
            merged["edge"].clip(lower=0)
            * merged["buy_share"]
            * merged["recent_notional"].apply(lambda x: math.log1p(max(x, 0)))
        )

        return merged.sort_values(["score", "recent_notional"], ascending=False).reset_index(drop=True)


class VolumeMomentumStrategy:
    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig.from_env()

    def score(self, outcome_df: pd.DataFrame) -> pd.DataFrame:
        if outcome_df.empty:
            return outcome_df

        cfg = self.config
        signals = outcome_df.copy()
        signals["signal"] = "hold"

        eligible = (
            signals["active"]
            & ~signals["closed"]
            & signals["market_price"].between(cfg.min_market_price, cfg.max_market_price, inclusive="both")
            & (signals["liquidity"] >= cfg.min_liquidity)
            & (signals["recent_trade_count"] >= cfg.min_recent_trades)
            & (signals["recent_notional"] >= cfg.min_recent_notional)
            & (signals["buy_share"] >= cfg.min_buy_share)
            & (signals["edge"] >= cfg.edge_threshold)
        )

        signals.loc[eligible, "signal"] = "buy"
        return signals

    def generate_signals(self, outcome_df: pd.DataFrame) -> pd.DataFrame:
        signals = self.score(outcome_df)
        if signals.empty:
            return signals
        cfg = self.config
        buys = signals[signals["signal"] == "buy"].nlargest(cfg.max_candidates, "score")
        return buys.reset_index(drop=True)

    def generate_exit_signals(self, positions_df: pd.DataFrame, scored_df: pd.DataFrame) -> pd.DataFrame:
        if positions_df.empty:
            return positions_df

        cfg = self.config
        market_state = scored_df[
            [
                "condition_id",
                "outcome_index",
                "market_price",
                "edge",
                "score",
                "question",
                "outcome",
            ]
        ].copy()
        merged = positions_df.merge(
            market_state,
            on=["condition_id", "outcome_index"],
            how="left",
            suffixes=("_position", ""),
        )
        merged["market_price"] = merged["market_price"].fillna(merged["current_price"])
        merged["edge"] = merged["edge"].fillna(0.0)
        merged["score"] = merged["score"].fillna(0.0)
        merged["return_pct"] = (merged["market_price"] - merged["entry_price"]) / merged["entry_price"].clip(lower=1e-9)

        merged["exit_reason"] = ""
        merged.loc[merged["edge"] <= cfg.exit_edge_threshold, "exit_reason"] = "edge_reversal"
        merged.loc[merged["return_pct"] >= cfg.take_profit_pct, "exit_reason"] = "take_profit"
        merged.loc[merged["return_pct"] <= -cfg.stop_loss_pct, "exit_reason"] = "stop_loss"

        return merged[merged["exit_reason"] != ""].reset_index(drop=True)


class PaperPortfolio:
    def __init__(self, config: PortfolioConfig | None = None):
        self.config = config or PortfolioConfig.from_env()
        self.cash = self.config.starting_cash
        self.positions: list[dict] = []
        self.orders: list[Order] = []

    def load_state(self, output_dir: Path) -> None:
        summary_path = output_dir / "summary.json"
        positions_path = output_dir / "positions.csv"
        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            self.cash = float(summary.get("cash", self.config.starting_cash))
        if positions_path.exists():
            positions = pd.read_csv(positions_path)
            self.positions = positions.to_dict("records")

    def mark_to_market(self, scored_df: pd.DataFrame) -> None:
        if not self.positions:
            return

        latest = scored_df.set_index(["condition_id", "outcome_index"])
        for position in self.positions:
            key = (position["condition_id"], position["outcome_index"])
            if key not in latest.index:
                continue
            row = latest.loc[key]
            current_price = float(row["market_price"])
            position["current_price"] = current_price
            position["mark_value"] = float(position["size"]) * current_price
            position["unrealized_pnl"] = position["mark_value"] - float(position["cost_basis"])
            position["edge"] = float(row["edge"])
            position["score"] = float(row["score"])

    def execute_exits(self, exit_signals: pd.DataFrame) -> None:
        if exit_signals.empty or not self.positions:
            return

        remaining_positions = []
        exits = {(row["condition_id"], int(row["outcome_index"])): row for _, row in exit_signals.iterrows()}

        for position in self.positions:
            key = (position["condition_id"], int(position["outcome_index"]))
            if key not in exits:
                remaining_positions.append(position)
                continue

            exit_row = exits[key]
            exit_price = float(exit_row["market_price"])
            notional = float(position["size"]) * exit_price
            self.cash += notional
            self.orders.append(
                Order(
                    condition_id=str(position["condition_id"]),
                    question=str(position["question"]),
                    outcome=str(position["outcome"]),
                    outcome_index=int(position["outcome_index"]),
                    side="sell",
                    price=exit_price,
                    size=float(position["size"]),
                    notional=notional,
                    edge=float(exit_row["edge"]),
                    score=float(exit_row["score"]),
                    reason=str(exit_row["exit_reason"]),
                )
            )

        self.positions = remaining_positions

    def execute(self, signals: pd.DataFrame) -> None:
        existing = {(position["condition_id"], int(position["outcome_index"])) for position in self.positions}
        for _, signal in signals.iterrows():
            if len(self.positions) >= self.config.max_positions:
                break
            if self.cash <= 0:
                break
            key = (str(signal["condition_id"]), int(signal["outcome_index"]))
            if key in existing:
                continue

            price = float(signal["market_price"])
            if price <= 0:
                continue

            notional = min(self.config.max_position_dollars, self.cash)
            size = notional / price
            order = Order(
                condition_id=str(signal["condition_id"]),
                question=str(signal["question"]),
                outcome=str(signal["outcome"]),
                outcome_index=int(signal["outcome_index"]),
                side="buy",
                price=price,
                size=size,
                notional=notional,
                edge=float(signal["edge"]),
                score=float(signal["score"]),
                reason="entry_signal",
            )
            self.orders.append(order)
            self.cash -= notional
            self.positions.append(
                {
                    "condition_id": order.condition_id,
                    "question": order.question,
                    "outcome": order.outcome,
                    "outcome_index": order.outcome_index,
                    "entry_price": order.price,
                    "current_price": order.price,
                    "size": order.size,
                    "cost_basis": order.notional,
                    "mark_value": order.size * order.price,
                    "unrealized_pnl": 0.0,
                    "edge": order.edge,
                    "score": order.score,
                }
            )
            existing.add(key)

    def orders_frame(self) -> pd.DataFrame:
        columns = [
            "condition_id",
            "question",
            "outcome",
            "outcome_index",
            "side",
            "price",
            "size",
            "notional",
            "edge",
            "score",
            "reason",
        ]
        if not self.orders:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([asdict(order) for order in self.orders], columns=columns)

    def positions_frame(self) -> pd.DataFrame:
        columns = [
            "condition_id",
            "question",
            "outcome",
            "outcome_index",
            "entry_price",
            "current_price",
            "size",
            "cost_basis",
            "mark_value",
            "unrealized_pnl",
            "edge",
            "score",
        ]
        if not self.positions:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(self.positions, columns=columns)

    def summary(self) -> dict[str, float | int]:
        mark_value = sum(position["mark_value"] for position in self.positions)
        equity = self.cash + mark_value
        return {
            "starting_cash": self.config.starting_cash,
            "cash": self.cash,
            "positions": len(self.positions),
            "orders": len(self.orders),
            "gross_exposure": mark_value,
            "equity": equity,
            "total_pnl": equity - self.config.starting_cash,
        }


class PaperTradingBot:
    def __init__(
        self,
        data_dir: Path | str = "data/current/polymarket",
        output_dir: Path | str = "output/paper_trading/polymarket",
        strategy: VolumeMomentumStrategy | None = None,
        portfolio: PaperPortfolio | None = None,
    ):
        self.snapshot = PolymarketSnapshot(data_dir=data_dir)
        self.output_dir = Path(output_dir)
        self.strategy = strategy or VolumeMomentumStrategy()
        self.portfolio = portfolio or PaperPortfolio()

    def _append_ledger(self, orders_df: pd.DataFrame, run_at: datetime) -> Path:
        ledger_path = self.output_dir / "ledger.csv"
        columns = [
            "run_at",
            "condition_id",
            "question",
            "outcome",
            "outcome_index",
            "side",
            "price",
            "size",
            "notional",
            "edge",
            "score",
            "reason",
        ]
        if orders_df.empty:
            if not ledger_path.exists():
                pd.DataFrame(columns=columns).to_csv(ledger_path, index=False)
            return ledger_path

        ledger_rows = orders_df.copy()
        ledger_rows["run_at"] = run_at.isoformat()
        ledger_rows = ledger_rows[columns]

        if ledger_path.exists():
            existing = pd.read_csv(ledger_path)
            ledger_rows = pd.concat([existing, ledger_rows], ignore_index=True)

        ledger_rows.to_csv(ledger_path, index=False)
        return ledger_path

    def run_once(self) -> dict[str, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        run_at = datetime.now(timezone.utc)

        outcome_df = self.snapshot.outcome_frame()
        scored = self.strategy.score(outcome_df)
        self.portfolio.load_state(self.output_dir)
        self.portfolio.mark_to_market(scored)
        starting_order_count = len(self.portfolio.orders)

        exit_signals = self.strategy.generate_exit_signals(self.portfolio.positions_frame(), scored)
        self.portfolio.execute_exits(exit_signals)

        orders = self.strategy.generate_signals(outcome_df)
        self.portfolio.execute(orders)
        self.portfolio.mark_to_market(scored)

        signals_path = self.output_dir / "signals.csv"
        orders_path = self.output_dir / "orders.csv"
        positions_path = self.output_dir / "positions.csv"
        summary_path = self.output_dir / "summary.json"
        exits_path = self.output_dir / "exits.csv"
        ledger_path = self.output_dir / "ledger.csv"
        exit_columns = [
            "condition_id",
            "question_position",
            "outcome_position",
            "outcome_index",
            "entry_price",
            "current_price",
            "market_price",
            "edge",
            "score",
            "return_pct",
            "exit_reason",
        ]

        scored.to_csv(signals_path, index=False)
        orders_df = self.portfolio.orders_frame()
        orders_df.to_csv(orders_path, index=False)
        new_orders_df = orders_df.iloc[starting_order_count:].reset_index(drop=True)
        self.portfolio.positions_frame().to_csv(positions_path, index=False)
        if exit_signals.empty:
            pd.DataFrame(columns=exit_columns).to_csv(exits_path, index=False)
        else:
            exit_signals.to_csv(exits_path, index=False)
        summary_path.write_text(json.dumps(self.portfolio.summary(), indent=2) + "\n")
        ledger_path = self._append_ledger(new_orders_df, run_at)

        return {
            "signals": signals_path,
            "orders": orders_path,
            "positions": positions_path,
            "exits": exits_path,
            "ledger": ledger_path,
            "summary": summary_path,
        }

    def run_loop(self, sleep_seconds: int = 60, iterations: int | None = None) -> dict[str, Path]:
        last_saved: dict[str, Path] = {}
        run_count = 0

        while True:
            run_count += 1
            print(f"Paper loop iteration {run_count}")
            last_saved = self.run_once()
            if iterations is not None and run_count >= iterations:
                break
            time.sleep(sleep_seconds)

        return last_saved
