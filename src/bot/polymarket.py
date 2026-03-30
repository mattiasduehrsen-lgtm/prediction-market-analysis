from __future__ import annotations

import asyncio
import functools
import json
import math
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.bot.live_executor import LiveExecutor, build_live_executor_if_enabled
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


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


@functools.lru_cache(maxsize=8192)
def _normalize_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    normalized = re.sub(r"\b(will|the|a|an|be|to|of|in|on|for)\b", " ", normalized)
    return " ".join(normalized.split())


@functools.lru_cache(maxsize=8192)
def _extract_key_terms(value: str) -> set[str]:
    stopwords = {
        "will",
        "what",
        "when",
        "where",
        "which",
        "who",
        "win",
        "wins",
        "winning",
        "lose",
        "loses",
        "tonight",
        "today",
        "tomorrow",
        "before",
        "after",
        "over",
        "under",
        "next",
        "market",
        "price",
        "probability",
        "yes",
        "no",
    }
    return {token for token in _normalize_text(value).split() if len(token) >= 3 and token not in stopwords}


@functools.lru_cache(maxsize=8192)
def _extract_numeric_tokens(value: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", str(value).lower()))


TEAM_ALIASES: dict[str, str] = {
    "chiefs": "kansas_city_chiefs",
    "kansas city": "kansas_city_chiefs",
    "kc": "kansas_city_chiefs",
    "eagles": "philadelphia_eagles",
    "philadelphia": "philadelphia_eagles",
    "sixers": "philadelphia_76ers",
    "76ers": "philadelphia_76ers",
    "lakers": "los_angeles_lakers",
    "la lakers": "los_angeles_lakers",
    "warriors": "golden_state_warriors",
    "gsw": "golden_state_warriors",
    "celtics": "boston_celtics",
    "bills": "buffalo_bills",
    "49ers": "san_francisco_49ers",
    "niners": "san_francisco_49ers",
    "yankees": "new_york_yankees",
    "mets": "new_york_mets",
    "dodgers": "los_angeles_dodgers",
}

POLITICAL_ALIASES: dict[str, str] = {
    "donald trump": "donald_trump",
    "trump": "donald_trump",
    "kamala harris": "kamala_harris",
    "harris": "kamala_harris",
    "joe biden": "joe_biden",
    "biden": "joe_biden",
    "ron desantis": "ron_desantis",
    "desantis": "ron_desantis",
    "pierre poilievre": "pierre_poilievre",
    "poilievre": "pierre_poilievre",
    "justin trudeau": "justin_trudeau",
    "trudeau": "justin_trudeau",
}

ECON_ALIAS_GROUPS: dict[str, str] = {
    "cpi": "cpi",
    "inflation": "cpi",
    "consumer price index": "cpi",
    "core cpi": "core_cpi",
    "core inflation": "core_cpi",
    "fed": "fed",
    "fomc": "fed",
    "federal reserve": "fed",
    "rate cut": "rate_cut",
    "rate hike": "rate_hike",
    "gdp": "gdp",
    "gross domestic product": "gdp",
    "unemployment": "unemployment",
    "nonfarm payrolls": "payrolls",
    "payrolls": "payrolls",
}

CRYPTO_ALIAS_GROUPS: dict[str, str] = {
    "bitcoin": "btc",
    "btc": "btc",
    "ethereum": "eth",
    "eth": "eth",
    "solana": "sol",
    "sol": "sol",
    "dogecoin": "doge",
    "doge": "doge",
    "xrp": "xrp",
}

MONTH_ALIASES: dict[str, str] = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}


def _extract_alias_entities(value: str, aliases: dict[str, str]) -> set[str]:
    normalized = _normalize_text(value)
    entities = set()
    for alias, canonical in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            entities.add(canonical)
    return entities


def _extract_date_tokens(value: str) -> set[str]:
    normalized = _normalize_text(value)
    tokens = set(_extract_numeric_tokens(normalized))
    words = normalized.split()
    for idx, word in enumerate(words):
        month = MONTH_ALIASES.get(word)
        if month:
            tokens.add(month)
            if idx + 1 < len(words) and words[idx + 1].isdigit():
                tokens.add(f"{month}-{int(words[idx + 1]):02d}")
    return tokens


def _extract_domain_aliases(value: str, groups: dict[str, str]) -> set[str]:
    normalized = _normalize_text(value)
    matches = set()
    for alias, canonical in groups.items():
        if re.search(rf"\b{re.escape(alias)}\b", normalized):
            matches.add(canonical)
    return matches


def _extract_threshold_direction(value: str) -> tuple[str | None, str | None]:
    normalized = _normalize_text(value)
    direction = None
    if any(term in normalized for term in ["above", "over", "greater than", "higher than", "at least"]):
        direction = "up"
    elif any(term in normalized for term in ["below", "under", "less than", "lower than", "at most"]):
        direction = "down"

    numbers = sorted(_extract_numeric_tokens(normalized))
    threshold = numbers[0] if numbers else None
    return direction, threshold


@functools.lru_cache(maxsize=8192)
def _infer_market_category(value: str) -> str:
    normalized = _normalize_text(value)
    if _extract_alias_entities(normalized, TEAM_ALIASES):
        return "sports"
    if _extract_alias_entities(normalized, POLITICAL_ALIASES):
        return "politics"
    if any(term in normalized for term in ["election", "vote", "senate", "house", "president", "prime minister"]):
        return "politics"
    if any(
        term in normalized for term in ["cpi", "inflation", "fed", "rate", "gdp", "unemployment", "payroll", "economy"]
    ):
        return "economics"
    if any(
        term in normalized
        for term in ["game", "match", "team", "score", "nfl", "nba", "mlb", "nhl", "soccer", "football"]
    ):
        return "sports"
    if any(term in normalized for term in ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana"]):
        return "crypto"
    return "general"


def _time_alignment_score(left_end: Any, right_end: Any) -> float:
    left_ts = pd.to_datetime(left_end, utc=True, errors="coerce")
    right_ts = pd.to_datetime(right_end, utc=True, errors="coerce")
    if pd.isna(left_ts) or pd.isna(right_ts):
        return 0.5
    try:
        delta_hours = abs((left_ts - right_ts).total_seconds()) / 3600
    except (OverflowError, Exception):
        return 0.0
    if delta_hours <= 3:
        return 1.0
    if delta_hours <= 12:
        return 0.75
    if delta_hours <= 24:
        return 0.5
    if delta_hours <= 48:
        return 0.25
    return 0.0


@functools.lru_cache(maxsize=65536)
def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(_normalize_text(left).split())
    right_tokens = set(_normalize_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return overlap / max(min(len(left_tokens), len(right_tokens)), 1)


def _cross_market_match_score(
    poly_question: str, poly_end_date: Any, kalshi_question: str, kalshi_close_time: Any
) -> tuple[float, dict[str, float | str]]:
    token_score = _token_overlap(poly_question, kalshi_question)
    poly_terms = _extract_key_terms(poly_question)
    kalshi_terms = _extract_key_terms(kalshi_question)
    poly_numbers = _extract_numeric_tokens(poly_question)
    kalshi_numbers = _extract_numeric_tokens(kalshi_question)
    number_score = (
        1.0
        if not poly_numbers and not kalshi_numbers
        else (
            len(poly_numbers & kalshi_numbers) / max(min(len(poly_numbers), len(kalshi_numbers)), 1)
            if poly_numbers and kalshi_numbers
            else 0.0
        )
    )
    poly_category = _infer_market_category(poly_question)
    kalshi_category = _infer_market_category(kalshi_question)
    category_score = 1.0 if poly_category == kalshi_category else 0.0
    time_score = _time_alignment_score(poly_end_date, kalshi_close_time)
    domain_score = 0.0
    alias_entity_score = 0.0
    if poly_category == "sports" and kalshi_category == "sports":
        poly_entities = _extract_alias_entities(poly_question, TEAM_ALIASES)
        kalshi_entities = _extract_alias_entities(kalshi_question, TEAM_ALIASES)
        alias_entity_score = (
            len(poly_entities & kalshi_entities) / max(min(len(poly_entities), len(kalshi_entities)), 1)
            if poly_entities and kalshi_entities
            else 0.0
        )
        domain_score = alias_entity_score
    elif poly_category == "politics" and kalshi_category == "politics":
        poly_entities = _extract_alias_entities(poly_question, POLITICAL_ALIASES)
        kalshi_entities = _extract_alias_entities(kalshi_question, POLITICAL_ALIASES)
        poly_dates = _extract_date_tokens(poly_question)
        kalshi_dates = _extract_date_tokens(kalshi_question)
        alias_entity_score = (
            len(poly_entities & kalshi_entities) / max(min(len(poly_entities), len(kalshi_entities)), 1)
            if poly_entities and kalshi_entities
            else 0.0
        )
        date_domain = (
            len(poly_dates & kalshi_dates) / max(min(len(poly_dates), len(kalshi_dates)), 1)
            if poly_dates and kalshi_dates
            else 0.5
        )
        domain_score = 0.7 * alias_entity_score + 0.3 * date_domain
    elif poly_category == "economics" and kalshi_category == "economics":
        poly_aliases = _extract_domain_aliases(poly_question, ECON_ALIAS_GROUPS)
        kalshi_aliases = _extract_domain_aliases(kalshi_question, ECON_ALIAS_GROUPS)
        alias_entity_score = (
            len(poly_aliases & kalshi_aliases) / max(min(len(poly_aliases), len(kalshi_aliases)), 1)
            if poly_aliases and kalshi_aliases
            else 0.0
        )
        poly_direction, poly_threshold = _extract_threshold_direction(poly_question)
        kalshi_direction, kalshi_threshold = _extract_threshold_direction(kalshi_question)
        direction_score = 1.0 if poly_direction == kalshi_direction and poly_direction is not None else 0.5
        threshold_score = 1.0 if poly_threshold == kalshi_threshold and poly_threshold is not None else 0.0
        domain_score = 0.5 * alias_entity_score + 0.25 * direction_score + 0.25 * threshold_score
    elif poly_category == "crypto" and kalshi_category == "crypto":
        poly_aliases = _extract_domain_aliases(poly_question, CRYPTO_ALIAS_GROUPS)
        kalshi_aliases = _extract_domain_aliases(kalshi_question, CRYPTO_ALIAS_GROUPS)
        alias_entity_score = (
            len(poly_aliases & kalshi_aliases) / max(min(len(poly_aliases), len(kalshi_aliases)), 1)
            if poly_aliases and kalshi_aliases
            else 0.0
        )
        poly_direction, poly_threshold = _extract_threshold_direction(poly_question)
        kalshi_direction, kalshi_threshold = _extract_threshold_direction(kalshi_question)
        direction_score = 1.0 if poly_direction == kalshi_direction and poly_direction is not None else 0.5
        threshold_score = 1.0 if poly_threshold == kalshi_threshold and poly_threshold is not None else 0.0
        date_domain = (
            len(_extract_date_tokens(poly_question) & _extract_date_tokens(kalshi_question))
            / max(min(len(_extract_date_tokens(poly_question)), len(_extract_date_tokens(kalshi_question))), 1)
            if _extract_date_tokens(poly_question) and _extract_date_tokens(kalshi_question)
            else 0.5
        )
        domain_score = 0.45 * alias_entity_score + 0.20 * direction_score + 0.20 * threshold_score + 0.15 * date_domain
    else:
        poly_dates = _extract_date_tokens(poly_question)
        kalshi_dates = _extract_date_tokens(kalshi_question)
        domain_score = (
            len(poly_dates & kalshi_dates) / max(min(len(poly_dates), len(kalshi_dates)), 1)
            if poly_dates and kalshi_dates
            else 0.0
        )
    lexical_entity_score = (
        len(poly_terms & kalshi_terms) / max(min(len(poly_terms), len(kalshi_terms)), 1)
        if poly_terms and kalshi_terms
        else 0.0
    )
    entity_score = max(lexical_entity_score, alias_entity_score)
    composite = (
        0.28 * token_score
        + 0.22 * entity_score
        + 0.10 * number_score
        + 0.15 * category_score
        + 0.10 * time_score
        + 0.15 * domain_score
    )
    if poly_numbers and kalshi_numbers and poly_numbers != kalshi_numbers:
        composite *= max(number_score, 0.25)
    if poly_category != kalshi_category:
        composite *= 0.5
    if time_score == 0.0:
        composite *= 0.8
    details: dict[str, float | str] = {
        "token_score": token_score,
        "entity_score": entity_score,
        "number_score": number_score,
        "category_score": category_score,
        "time_score": time_score,
        "domain_score": domain_score,
        "poly_category": poly_category,
        "kalshi_category": kalshi_category,
    }
    return composite, details


def _confidence_bucket(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.65:
        return "medium"
    if value > 0:
        return "low"
    return "none"


def _support_bucket(value: float) -> str:
    if value >= 0.12:
        return "strong_confirm"
    if value > 0:
        return "confirm"
    if value <= -0.12:
        return "strong_disagree"
    if value < 0:
        return "disagree"
    return "neutral"


def _persistence_bucket(signal_runs: int, signal_age_seconds: float) -> str:
    if signal_runs <= 1:
        return "fresh"
    if signal_runs <= 3 and signal_age_seconds <= 3600:
        return "building"
    if signal_runs <= 8 and signal_age_seconds <= 6 * 3600:
        return "persistent"
    return "stale"


def _entry_timing_bucket(signal_runs: int) -> str:
    if signal_runs <= 1:
        return "first_entry"
    if signal_runs <= 3:
        return "early_confirmation"
    if signal_runs <= 6:
        return "mid_persistence"
    return "late_entry"


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
    edge_threshold: float = 0.005
    edge_ratio_threshold: float = 0.01
    min_recent_trades: int = 1
    min_recent_notional: float = 10.0
    min_liquidity: float = 5000.0
    min_buy_share: float = 0.52
    min_market_price: float = 0.15
    max_market_price: float = 0.85
    lookback_seconds: int = 21600
    max_candidates: int = 5
    max_seconds_since_last_trade: int = 7200
    min_hours_to_expiry: float = 2.0
    max_hours_to_expiry: float = 48.0
    exit_edge_threshold: float = -0.01
    take_profit_pct: float = 0.15
    stop_loss_pct: float = 0.07
    trailing_stop_drawdown_pct: float = 0.08
    max_holding_seconds: int = 86400
    min_cross_market_overlap: float = 0.6
    kalshi_confirmation_bonus: float = 0.15
    kalshi_disagreement_penalty: float = 0.20
    kalshi_price_gap_threshold: float = 0.05
    min_price_momentum: float = 0.003

    @classmethod
    def from_env(cls) -> StrategyConfig:
        return cls(
            edge_threshold=_env_float("PAPER_EDGE_THRESHOLD", 0.005),
            edge_ratio_threshold=_env_float("PAPER_EDGE_RATIO_THRESHOLD", 0.01),
            min_recent_trades=_env_int("PAPER_MIN_RECENT_TRADES", 1),
            min_recent_notional=_env_float("PAPER_MIN_RECENT_NOTIONAL", 10.0),
            min_liquidity=_env_float("PAPER_MIN_LIQUIDITY", 5000.0),
            min_buy_share=_env_float("PAPER_MIN_BUY_SHARE", 0.52),
            min_market_price=_env_float("PAPER_MIN_MARKET_PRICE", 0.15),
            max_market_price=_env_float("PAPER_MAX_MARKET_PRICE", 0.85),
            lookback_seconds=_env_int("PAPER_LOOKBACK_SECONDS", 21600),
            max_candidates=_env_int("PAPER_MAX_CANDIDATES", 5),
            max_seconds_since_last_trade=_env_int("PAPER_MAX_SECONDS_SINCE_LAST_TRADE", 7200),
            min_hours_to_expiry=_env_float("PAPER_MIN_HOURS_TO_EXPIRY", 2.0),
            max_hours_to_expiry=_env_float("PAPER_MAX_HOURS_TO_EXPIRY", 48.0),
            exit_edge_threshold=_env_float("PAPER_EXIT_EDGE_THRESHOLD", -0.01),
            take_profit_pct=_env_float("PAPER_TAKE_PROFIT_PCT", 0.25),
            stop_loss_pct=_env_float("PAPER_STOP_LOSS_PCT", 0.07),
            trailing_stop_drawdown_pct=_env_float("PAPER_TRAILING_STOP_DRAWDOWN_PCT", 0.12),
            max_holding_seconds=_env_int("PAPER_MAX_HOLDING_SECONDS", 86400),
            min_cross_market_overlap=_env_float("PAPER_MIN_CROSS_MARKET_OVERLAP", 0.35),
            kalshi_confirmation_bonus=_env_float("PAPER_KALSHI_CONFIRMATION_BONUS", 0.15),
            kalshi_disagreement_penalty=_env_float("PAPER_KALSHI_DISAGREEMENT_PENALTY", 0.20),
            kalshi_price_gap_threshold=_env_float("PAPER_KALSHI_PRICE_GAP_THRESHOLD", 0.05),
            min_price_momentum=_env_float("PAPER_MIN_PRICE_MOMENTUM", 0.003),
        )


@dataclass
class PortfolioConfig:
    starting_cash: float = 1000.0
    min_position_dollars: float = 25.0
    max_position_dollars: float = 100.0
    max_positions: int = 5
    max_gross_exposure_pct: float = 0.60
    cooldown_seconds: int = 1800

    @classmethod
    def from_env(cls) -> PortfolioConfig:
        return cls(
            starting_cash=_env_float("PAPER_STARTING_CASH", 1000.0),
            min_position_dollars=_env_float("PAPER_MIN_POSITION_DOLLARS", 25.0),
            max_position_dollars=_env_float("PAPER_MAX_POSITION_DOLLARS", 100.0),
            max_positions=_env_int("PAPER_MAX_POSITIONS", 5),
            max_gross_exposure_pct=_env_float("PAPER_MAX_GROSS_EXPOSURE_PCT", 0.60),
            cooldown_seconds=_env_int("PAPER_COOLDOWN_SECONDS", 1800),
        )


@dataclass
class Order:
    position_id: str
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
    conviction: float = 0.0
    buy_share: float = 0.0
    recent_trade_count: int = 0
    recent_notional: float = 0.0
    market_price: float = 0.0
    price_gap_pct: float = 0.0
    signal_runs: int = 1
    signal_age_seconds: float = 0.0
    signal_persistence_bucket: str = "fresh"
    kalshi_match_score: float = 0.0
    kalshi_match_bucket: str = "none"
    cross_market_support: float = 0.0
    cross_market_support_bucket: str = "neutral"
    cross_market_reason: str = ""
    reason: str = ""
    holding_seconds: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl_after: float = 0.0
    cash_after: float = 0.0
    gross_exposure_after: float = 0.0
    equity_after: float = 0.0
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

    def _load_order_books(self) -> pd.DataFrame:
        ob_path = self.data_dir / "order_books.parquet"
        if ob_path.exists():
            return pd.read_parquet(ob_path)
        return pd.DataFrame()

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
                weighted_price=("price", lambda s: (s * recent.loc[s.index, "size"]).sum()),
                buy_share=("buy_flag", "mean"),
                last_trade_price=("price", "last"),
                last_trade_at=("timestamp", "max"),
            ).reset_index()
            recent_agg["recent_vwap"] = recent_agg["weighted_price"] / recent_agg["recent_volume_shares"].clip(
                lower=1e-9
            )
            recent_agg = recent_agg.drop(columns=["weighted_price"])

        # Momentum: compare VWAP in the early half of the window vs the late half.
        # Rising prices → positive momentum → stronger buy signal.
        mid_cutoff = cutoff + pd.Timedelta(seconds=lookback_seconds / 2)
        early_trades = recent[recent["timestamp"] < mid_cutoff].copy()
        late_trades = recent[recent["timestamp"] >= mid_cutoff].copy()

        def _half_vwap(df: pd.DataFrame, col: str) -> pd.DataFrame:
            if df.empty:
                return pd.DataFrame(columns=["condition_id", "outcome", "outcome_index", col])
            df = df.copy()
            df["_notional"] = df["size"] * df["price"]
            g = df.groupby(["condition_id", "outcome", "outcome_index"], dropna=False)
            result = (g["_notional"].sum() / g["size"].sum().clip(lower=1e-9)).reset_index()
            result.columns = ["condition_id", "outcome", "outcome_index", col]
            return result

        early_vwap_df = _half_vwap(early_trades, "early_vwap")
        late_vwap_df = _half_vwap(late_trades, "late_vwap")

        merged = outcomes_df.merge(
            recent_agg,
            on=["condition_id", "outcome", "outcome_index"],
            how="left",
        ).merge(
            early_vwap_df,
            on=["condition_id", "outcome", "outcome_index"],
            how="left",
        ).merge(
            late_vwap_df,
            on=["condition_id", "outcome", "outcome_index"],
            how="left",
        )

        for col in ["recent_trade_count", "recent_volume_shares", "recent_notional", "buy_share"]:
            merged[col] = merged[col].fillna(0)

        merged["recent_vwap"] = merged["recent_vwap"].fillna(merged["market_price"])
        merged["early_vwap"] = merged["early_vwap"].fillna(merged["market_price"])
        merged["late_vwap"] = merged["late_vwap"].fillna(merged["market_price"])
        merged["last_trade_price"] = merged["last_trade_price"].fillna(merged["market_price"])
        merged["price_momentum"] = merged["late_vwap"] - merged["early_vwap"]
        merged["edge"] = merged["recent_vwap"] - merged["market_price"]
        merged["edge_ratio"] = merged["edge"] / merged["market_price"].clip(lower=1e-9)
        merged["seconds_since_last_trade"] = (
            latest_ts - pd.to_datetime(merged["last_trade_at"], utc=True, errors="coerce")
        ).dt.total_seconds()
        merged["seconds_since_last_trade"] = merged["seconds_since_last_trade"].fillna(float("inf"))
        merged["flow_imbalance"] = (merged["buy_share"] - 0.5).clip(lower=0)
        merged["end_date"] = pd.to_datetime(merged["end_date"], utc=True, errors="coerce")
        merged["hours_to_expiry"] = (merged["end_date"] - latest_ts).dt.total_seconds() / 3600
        merged["hours_to_expiry"] = merged["hours_to_expiry"].fillna(float("inf"))

        freshness = 1 / (1 + (merged["seconds_since_last_trade"] / 300).clip(lower=0))
        liquidity_bonus = merged["recent_notional"].apply(lambda x: math.log1p(max(x, 0)))
        momentum_signal = merged["price_momentum"].clip(lower=0)
        edge_signal = merged["edge"].clip(lower=0)
        # Boost score for markets resolving sooner — they move faster so momentum matters more.
        expiry_boost = 1 + (1 / (1 + merged["hours_to_expiry"].clip(lower=1) / 24)).clip(lower=0, upper=0.5)
        merged["score"] = (
            (edge_signal + momentum_signal * 2)
            * (1 + merged["edge_ratio"].clip(lower=0))
            * (merged["flow_imbalance"].clip(lower=0) + 0.05)
            * freshness
            * liquidity_bonus
            * expiry_boost
        )

        # Merge order book imbalance from pmxt data if available.
        ob_df = self._load_order_books()
        if not ob_df.empty and "condition_id" in ob_df.columns:
            ob_keep = ob_df[["condition_id", "outcome_index", "ob_imbalance", "spread", "best_bid", "best_ask"]].copy()
            ob_keep["outcome_index"] = ob_keep["outcome_index"].astype(int)
            merged = merged.merge(ob_keep, on=["condition_id", "outcome_index"], how="left")
        else:
            merged["ob_imbalance"] = 0.0
            merged["spread"] = math.nan
            merged["best_bid"] = math.nan
            merged["best_ask"] = math.nan

        merged["ob_imbalance"] = merged["ob_imbalance"].fillna(0.0)

        # Boost score when order book shows strong buying pressure.
        ob_boost = (merged["ob_imbalance"].clip(lower=0) * 0.5 + 1.0)
        merged["score"] = merged["score"] * ob_boost

        return merged.sort_values(["score", "recent_notional"], ascending=False).reset_index(drop=True)


class KalshiSnapshot:
    def __init__(self, data_dir: Path | str = "data/current/kalshi"):
        self.data_dir = Path(data_dir)

    def load(self) -> tuple[pd.DataFrame, pd.DataFrame] | tuple[None, None]:
        try:
            markets = _load_table(_select_existing(self.data_dir, "markets"))
            trades = _load_table(_select_existing(self.data_dir, "trades"))
        except FileNotFoundError:
            return None, None
        return markets, trades

    def signal_frame(self, latest_ts: pd.Timestamp) -> pd.DataFrame:
        markets, trades = self.load()
        if markets is None or trades is None or markets.empty:
            return pd.DataFrame()

        frame = markets.copy()

        def _series(column: str, default: Any) -> pd.Series:
            if column in frame.columns:
                return frame[column]
            return pd.Series([default] * len(frame), index=frame.index)

        frame["status"] = _series("status", "").fillna("").astype(str).str.lower()
        # Only keep live, tradeable markets — skip initialized (not yet open), settled, finalized.
        frame = frame[frame["status"].isin(["active", "open"])]
        if frame.empty:
            return pd.DataFrame()

        def _to_price(series: pd.Series) -> pd.Series:
            """Convert Kalshi price to 0-1 range. Handles both old integer-cents and new dollar formats."""
            numeric = pd.to_numeric(series, errors="coerce")
            # If values are clearly in cents (>1.0), divide by 100. Otherwise already in dollars.
            return numeric.where(numeric <= 1.0, numeric / 100.0)

        # Read prices — model stores them as yes_bid (parsed float) but also check raw _dollars fields
        # in case the parquet was written before models.py parsed them correctly.
        yes_bid = _to_price(_series("yes_bid", math.nan))
        yes_ask = _to_price(_series("yes_ask", math.nan))
        last_price = _to_price(_series("last_price", math.nan))
        # Fallback: raw API dollar-string fields stored verbatim in older snapshots
        if yes_ask.isna().all():
            yes_ask = _to_price(pd.to_numeric(_series("yes_ask_dollars", math.nan), errors="coerce"))
        if yes_bid.isna().all():
            yes_bid = _to_price(pd.to_numeric(_series("yes_bid_dollars", math.nan), errors="coerce"))
        if last_price.isna().all():
            last_price = _to_price(pd.to_numeric(_series("last_price_dollars", math.nan), errors="coerce"))
        frame["kalshi_yes_price"] = yes_ask.fillna(yes_bid).fillna(last_price)
        # Drop rows with no price — they are pre-created but inactive markets with no liquidity.
        frame = frame[frame["kalshi_yes_price"].notna()]
        if frame.empty:
            return pd.DataFrame()
        frame["kalshi_no_price"] = 1 - frame["kalshi_yes_price"]
        frame["kalshi_mid_price"] = pd.concat([yes_bid, yes_ask], axis=1).mean(axis=1).fillna(frame["kalshi_yes_price"])
        frame["kalshi_question"] = _series("title", "").fillna("").astype(str)
        frame["kalshi_market_norm"] = frame["kalshi_question"].map(_normalize_text)
        frame["kalshi_category"] = frame["kalshi_question"].map(_infer_market_category)
        frame["kalshi_key_terms"] = frame["kalshi_question"].map(
            lambda value: " ".join(sorted(_extract_key_terms(value)))
        )
        frame["kalshi_yes_label"] = _series("yes_sub_title", "Yes").fillna("Yes").astype(str)
        frame["kalshi_no_label"] = _series("no_sub_title", "No").fillna("No").astype(str)
        frame["kalshi_volume"] = pd.to_numeric(_series("volume", 0.0), errors="coerce").fillna(0.0)
        frame["kalshi_open_interest"] = pd.to_numeric(_series("open_interest", 0.0), errors="coerce").fillna(0.0)
        frame["close_time"] = pd.to_datetime(_series("close_time", pd.NaT), utc=True, errors="coerce")
        frame["kalshi_hours_to_close"] = (frame["close_time"] - latest_ts).dt.total_seconds() / 3600

        if trades is None or trades.empty:
            frame["kalshi_buy_share"] = 0.5
            frame["kalshi_recent_trade_count"] = 0
            return frame

        trades = trades.copy()
        trades["created_time"] = pd.to_datetime(trades["created_time"], utc=True, errors="coerce")
        trades = trades.dropna(subset=["created_time"])
        recent = trades[
            trades["created_time"] >= latest_ts - pd.Timedelta(seconds=StrategyConfig.from_env().lookback_seconds)
        ]
        if recent.empty:
            frame["kalshi_buy_share"] = 0.5
            frame["kalshi_recent_trade_count"] = 0
            return frame

        recent["yes_price_norm"] = (
            pd.to_numeric(recent["yes_price"] if "yes_price" in recent.columns else math.nan, errors="coerce") / 100.0
        )
        recent["buy_yes_flag"] = (
            (
                recent["taker_side"]
                if "taker_side" in recent.columns
                else pd.Series([""] * len(recent), index=recent.index)
            )
            .fillna("")
            .astype(str)
            .str.lower()
            .eq("yes")
            .astype(float)
        )
        trade_agg = (
            recent.groupby("ticker", dropna=False)
            .agg(
                kalshi_recent_trade_count=("trade_id", "count"),
                kalshi_recent_yes_price=("yes_price_norm", "mean"),
                kalshi_buy_share=("buy_yes_flag", "mean"),
            )
            .reset_index()
        )
        return frame.merge(trade_agg, on="ticker", how="left")


def _merge_cross_market_data(
    outcome_df: pd.DataFrame, kalshi_df: pd.DataFrame, cfg: StrategyConfig, latest_ts: pd.Timestamp
) -> pd.DataFrame:
    enriched = outcome_df.copy()
    enriched["kalshi_match_found"] = False
    enriched["kalshi_match_score"] = 0.0
    enriched["kalshi_match_components"] = ""
    enriched["kalshi_question"] = ""
    enriched["kalshi_yes_price"] = math.nan
    enriched["kalshi_probability"] = math.nan
    enriched["kalshi_price_gap"] = math.nan
    enriched["kalshi_confirms"] = False
    enriched["kalshi_disagrees"] = False
    enriched["kalshi_alignment_score"] = 0.0
    enriched["cross_market_support"] = 0.0
    enriched["kalshi_match_bucket"] = "none"
    enriched["cross_market_support_bucket"] = "neutral"
    enriched["cross_market_reason"] = "no_kalshi_match"

    if kalshi_df.empty:
        return enriched

    # Cap Kalshi records to the top 2000 by volume so matching stays fast.
    # These are the most liquid markets and most likely to match Polymarket.
    cap_df = kalshi_df.copy()
    if "kalshi_volume" in cap_df.columns:
        cap_df = cap_df.nlargest(2000, "kalshi_volume")
    else:
        cap_df = cap_df.head(2000)
    kalshi_records = cap_df.to_dict("records")

    # Build an inverted index: keyword -> list of kalshi record indices.
    # This means each Polymarket market is only scored against Kalshi markets
    # that share at least one keyword, instead of every Kalshi market.
    kalshi_index: dict[str, list[int]] = {}
    for i, record in enumerate(kalshi_records):
        for term in _extract_key_terms(str(record.get("kalshi_question", ""))):
            kalshi_index.setdefault(term, []).append(i)

    for idx, row in enriched.iterrows():
        question = str(row.get("question", ""))
        if not question:
            continue

        # Find only Kalshi records that share at least one keyword
        candidate_indices: set[int] = set()
        for term in _extract_key_terms(question):
            candidate_indices.update(kalshi_index.get(term, []))

        best_match: dict[str, Any] | None = None
        best_score = 0.0
        best_details: dict[str, float | str] | None = None
        for i in candidate_indices:
            candidate = kalshi_records[i]
            score, details = _cross_market_match_score(
                question,
                row.get("end_date"),
                str(candidate.get("kalshi_question", "")),
                candidate.get("close_time"),
            )
            if score > best_score:
                best_score = score
                best_match = candidate
                best_details = details

        if best_match is None or best_score < cfg.min_cross_market_overlap:
            continue

        kalshi_yes_price = float(best_match.get("kalshi_yes_price", math.nan))
        if row["outcome_index"] == 0:
            comparable_price = kalshi_yes_price
        else:
            comparable_price = 1 - kalshi_yes_price if pd.notna(kalshi_yes_price) else math.nan

        price_gap = comparable_price - float(row["market_price"]) if pd.notna(comparable_price) else math.nan
        confirms = pd.notna(price_gap) and price_gap >= cfg.kalshi_price_gap_threshold
        disagrees = pd.notna(price_gap) and price_gap <= -cfg.kalshi_price_gap_threshold
        alignment_score = (
            0.0 if pd.isna(price_gap) else _clamp(abs(price_gap) / max(cfg.kalshi_price_gap_threshold * 2, 1e-9))
        )
        support = 0.0
        if confirms:
            support = cfg.kalshi_confirmation_bonus * alignment_score
        elif disagrees:
            support = -cfg.kalshi_disagreement_penalty * alignment_score

        enriched.at[idx, "kalshi_match_found"] = True
        enriched.at[idx, "kalshi_match_score"] = best_score
        if best_details is not None:
            enriched.at[idx, "kalshi_match_components"] = (
                f"token={best_details['token_score']:.0%}, entity={best_details['entity_score']:.0%}, "
                f"number={best_details['number_score']:.0%}, category={best_details['category_score']:.0%}, "
                f"time={best_details['time_score']:.0%}, domain={best_details['domain_score']:.0%}"
            )
        enriched.at[idx, "kalshi_question"] = str(best_match.get("kalshi_question", ""))
        enriched.at[idx, "kalshi_yes_price"] = kalshi_yes_price
        enriched.at[idx, "kalshi_probability"] = comparable_price
        enriched.at[idx, "kalshi_price_gap"] = price_gap
        enriched.at[idx, "kalshi_confirms"] = confirms
        enriched.at[idx, "kalshi_disagrees"] = disagrees
        enriched.at[idx, "kalshi_alignment_score"] = alignment_score
        enriched.at[idx, "cross_market_support"] = support
        enriched.at[idx, "kalshi_match_bucket"] = _confidence_bucket(best_score)
        enriched.at[idx, "cross_market_support_bucket"] = _support_bucket(support)
        if confirms:
            reason = f"kalshi_confirms gap={price_gap:.1%} match={best_score:.0%}"
        elif disagrees:
            reason = f"kalshi_disagrees gap={price_gap:.1%} match={best_score:.0%}"
        else:
            reason = f"kalshi_neutral gap={0.0 if pd.isna(price_gap) else price_gap:.1%} match={best_score:.0%}"
        if best_details is not None:
            reason = (
                f"{reason} token={best_details['token_score']:.0%} "
                f"time={best_details['time_score']:.0%} domain={best_details['domain_score']:.0%}"
            )
        enriched.at[idx, "cross_market_reason"] = reason

    return enriched


class VolumeMomentumStrategy:
    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig.from_env()

    def score(self, outcome_df: pd.DataFrame) -> pd.DataFrame:
        if outcome_df.empty:
            return outcome_df

        cfg = self.config
        signals = outcome_df.copy()
        signals["signal"] = "hold"
        signals["conviction"] = 0.0
        signals["entry_reason"] = ""
        signals["hours_to_expiry"] = signals["hours_to_expiry"].fillna(float("inf"))
        signals["seconds_since_last_trade"] = signals["seconds_since_last_trade"].fillna(float("inf"))
        if "cross_market_support" not in signals.columns:
            signals["cross_market_support"] = 0.0
        else:
            signals["cross_market_support"] = signals["cross_market_support"].fillna(0.0)
        if "cross_market_reason" not in signals.columns:
            signals["cross_market_reason"] = "no_kalshi_match"
        else:
            signals["cross_market_reason"] = signals["cross_market_reason"].fillna("no_kalshi_match")
        if "kalshi_disagrees" not in signals.columns:
            signals["kalshi_disagrees"] = False
        else:
            signals["kalshi_disagrees"] = signals["kalshi_disagrees"].fillna(False)
        if "kalshi_confirms" not in signals.columns:
            signals["kalshi_confirms"] = False
        else:
            signals["kalshi_confirms"] = signals["kalshi_confirms"].fillna(False)
        if "signal_age_seconds" not in signals.columns:
            signals["signal_age_seconds"] = 0.0
        else:
            signals["signal_age_seconds"] = signals["signal_age_seconds"].fillna(0.0)
        if "signal_runs" not in signals.columns:
            signals["signal_runs"] = 1
        else:
            signals["signal_runs"] = signals["signal_runs"].fillna(1)
        if "signal_persistence_bucket" not in signals.columns:
            signals["signal_persistence_bucket"] = "fresh"
        else:
            signals["signal_persistence_bucket"] = signals["signal_persistence_bucket"].fillna("fresh")

        base_eligible = (
            signals["active"]
            & ~signals["closed"]
            & signals["market_price"].between(cfg.min_market_price, cfg.max_market_price, inclusive="both")
            & (signals["liquidity"] >= cfg.min_liquidity)
            & (signals["hours_to_expiry"] >= cfg.min_hours_to_expiry)
            & (signals["hours_to_expiry"] <= cfg.max_hours_to_expiry)
            & ~signals["kalshi_disagrees"]
        )

        # Signal 1: Cross-exchange mispricing — Kalshi prices this outcome meaningfully higher than Polymarket.
        # Two independent exchanges disagreeing on probability is a real, exploitable edge.
        kalshi_price_gap = signals["kalshi_price_gap"].fillna(0.0)
        kalshi_eligible = (
            base_eligible
            & signals["kalshi_confirms"].fillna(False)
            & (kalshi_price_gap >= cfg.kalshi_price_gap_threshold)
        )

        # Signal 2: Order book buying pressure — more buyers than sellers right now in the live order book.
        # Requires a meaningful imbalance (>20% net buyer) confirmed by liquidity.
        ob_imbalance = signals["ob_imbalance"].fillna(0.0) if "ob_imbalance" in signals.columns else pd.Series(0.0, index=signals.index)
        ob_eligible = (
            base_eligible
            & (ob_imbalance >= 0.20)
            & (signals["liquidity"] >= cfg.min_liquidity * 2)
            & (signals["seconds_since_last_trade"] <= cfg.max_seconds_since_last_trade)
        )

        # Signal 3: VWAP edge confirmed by either Kalshi or order book.
        # Pure momentum alone was shown to lose — require a second confirming signal.
        vwap_confirmed = (
            base_eligible
            & (signals["recent_trade_count"] >= cfg.min_recent_trades)
            & (signals["recent_notional"] >= cfg.min_recent_notional)
            & (signals["buy_share"] >= cfg.min_buy_share)
            & (signals["edge"] >= cfg.edge_threshold)
            & (signals["edge_ratio"] >= cfg.edge_ratio_threshold)
            & (signals["seconds_since_last_trade"] <= cfg.max_seconds_since_last_trade)
            & (signals["last_trade_price"] >= signals["market_price"])
            & (kalshi_eligible | (ob_imbalance >= 0.10))  # must have cross-market or order book support
        )

        eligible = kalshi_eligible | ob_eligible | vwap_confirmed

        # Conviction: weight cross-market and order book signals heavily since they're higher quality.
        kalshi_component = (kalshi_price_gap / max(cfg.kalshi_price_gap_threshold * 3, 1e-9)).apply(_clamp)
        ob_component = (ob_imbalance / 0.5).apply(_clamp)
        edge_component = (signals["edge"] / max(cfg.edge_threshold * 2, 1e-9)).apply(_clamp)
        flow_component = ((signals["buy_share"] - cfg.min_buy_share) / max(1 - cfg.min_buy_share, 1e-9)).apply(_clamp)
        notional_component = (
            signals["recent_notional"].apply(lambda x: math.log1p(max(x, 0)))
            / max(math.log1p(cfg.min_recent_notional * 8), 1e-9)
        ).apply(_clamp)

        signals["conviction"] = (
            0.35 * kalshi_component   # cross-exchange mispricing is strongest signal
            + 0.25 * ob_component     # live order book imbalance
            + 0.20 * edge_component   # VWAP edge
            + 0.10 * flow_component   # buy/sell ratio
            + 0.10 * notional_component  # market activity
        )
        persistence_boost = (signals["signal_runs"] - 1).clip(lower=0, upper=3) * 0.02
        stale_penalty = ((signals["signal_age_seconds"] - 6 * 3600).clip(lower=0) / (24 * 3600)).clip(upper=0.15)
        signals["conviction"] = (signals["conviction"] + persistence_boost - stale_penalty).clip(lower=0.0, upper=1.0)
        signals["score"] = signals["score"] * (1 + signals["cross_market_support"]) * (1 + ob_component * 0.5)

        signals.loc[eligible, "signal"] = "buy"
        eligible_rows = signals.loc[eligible]
        signals.loc[eligible, "entry_reason"] = eligible_rows.apply(
            lambda row: (
                f"kalshi_gap={row.get('kalshi_price_gap', 0) or 0:.3f}, "
                f"ob_imbalance={row.get('ob_imbalance', 0) or 0:.2f}, "
                f"edge={row['edge']:.3f}, buy_share={row['buy_share']:.1%}, "
                f"expiry={row['hours_to_expiry']:.1f}h, signal_runs={int(row['signal_runs'])}, "
                f"{row['cross_market_reason']}"
            ),
            axis=1,
        )
        return signals

    def generate_signals(self, scored_df: pd.DataFrame) -> pd.DataFrame:
        if scored_df.empty:
            return scored_df
        buys = scored_df[scored_df["signal"] == "buy"].nlargest(self.config.max_candidates, ["conviction", "score"])
        return buys.reset_index(drop=True)

    def generate_exit_signals(
        self, positions_df: pd.DataFrame, scored_df: pd.DataFrame, run_at: datetime
    ) -> pd.DataFrame:
        if positions_df.empty:
            return positions_df
        if scored_df.empty:
            return pd.DataFrame(columns=["position_id", "exit_reason"])

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
                "buy_share",
                "recent_trade_count",
                "recent_notional",
                "closed",
                "active",
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
        merged["buy_share"] = merged["buy_share"].fillna(0.0)
        merged["recent_trade_count"] = merged["recent_trade_count"].fillna(0)
        merged["recent_notional"] = merged["recent_notional"].fillna(0.0)
        merged["closed"] = merged["closed"].fillna(False)
        merged["active"] = merged["active"].fillna(True)
        merged["return_pct"] = (merged["market_price"] - merged["entry_price"]) / merged["entry_price"].clip(lower=1e-9)
        merged["opened_at"] = pd.to_datetime(merged["opened_at"], utc=True, errors="coerce")
        merged["holding_seconds"] = (run_at - merged["opened_at"]).dt.total_seconds().fillna(0.0)
        merged["drawdown_from_peak_pct"] = (merged["market_price"] - merged["peak_price"]) / merged["peak_price"].clip(
            lower=1e-9
        )

        merged["exit_reason"] = ""
        # Apply exits in priority order: higher priority assignments overwrite lower ones.
        # market_inactive < max_hold < edge_reversal < momentum_reversal < trailing_stop < stop_loss < take_profit
        merged.loc[merged["closed"] | ~merged["active"], "exit_reason"] = "market_inactive"
        merged.loc[merged["holding_seconds"] >= cfg.max_holding_seconds, "exit_reason"] = "max_hold"
        merged.loc[merged["edge"] <= cfg.exit_edge_threshold, "exit_reason"] = "edge_reversal"
        if "price_momentum" in merged.columns:
            merged.loc[
                (merged["price_momentum"] < -cfg.min_price_momentum)
                & (merged["return_pct"] > -cfg.stop_loss_pct / 2),
                "exit_reason",
            ] = "momentum_reversal"
        merged.loc[
            (merged["return_pct"] > 0) & (merged["drawdown_from_peak_pct"] <= -cfg.trailing_stop_drawdown_pct),
            "exit_reason",
        ] = "trailing_stop"
        # stop_loss and take_profit always win — applied last so they can't be overwritten.
        merged.loc[merged["return_pct"] <= -cfg.stop_loss_pct, "exit_reason"] = "stop_loss"
        merged.loc[merged["return_pct"] >= cfg.take_profit_pct, "exit_reason"] = "take_profit"

        return merged[merged["exit_reason"] != ""].reset_index(drop=True)


class PaperPortfolio:
    def __init__(self, config: PortfolioConfig | None = None, live_executor: LiveExecutor | None = None):
        self.config = config or PortfolioConfig.from_env()
        self.live_executor = live_executor
        self.cash = self.config.starting_cash
        self.positions: list[dict[str, Any]] = []
        self.orders: list[Order] = []
        self.last_exit_at: dict[tuple[str, int], datetime] = {}
        self.realized_pnl = 0.0

    def load_state(self, output_dir: Path) -> None:
        self.cash = self.config.starting_cash
        self.positions = []
        self.orders = []
        self.last_exit_at = {}
        self.realized_pnl = 0.0

        summary_path = output_dir / "summary.json"
        positions_path = output_dir / "positions.csv"
        ledger_path = output_dir / "ledger.csv"

        if summary_path.exists():
            summary = json.loads(summary_path.read_text())
            self.cash = float(summary.get("cash", self.config.starting_cash))
            self.realized_pnl = float(summary.get("realized_pnl", 0.0))

        if positions_path.exists():
            positions = pd.read_csv(positions_path)
            self.positions = positions.to_dict("records")

        if ledger_path.exists():
            ledger = pd.read_csv(ledger_path)
            if not ledger.empty:
                sells = ledger[ledger["side"] == "sell"].copy()
                if not sells.empty:
                    sells["run_at"] = pd.to_datetime(sells["run_at"], utc=True, errors="coerce")
                    for _, row in sells.iterrows():
                        if pd.isna(row["run_at"]):
                            continue
                        key = (str(row["condition_id"]), int(row["outcome_index"]))
                        self.last_exit_at[key] = row["run_at"].to_pydatetime()

    def mark_to_market(self, scored_df: pd.DataFrame, run_at: datetime) -> None:
        if not self.positions or scored_df.empty:
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
            position["peak_price"] = max(float(position.get("peak_price", position["entry_price"])), current_price)
            peak_mark_value = float(position["size"]) * float(position["peak_price"])
            position["max_unrealized_pnl"] = peak_mark_value - float(position["cost_basis"])
            position["last_updated_at"] = run_at.isoformat()

    def _gross_exposure(self) -> float:
        return sum(float(position.get("mark_value", 0.0)) for position in self.positions)

    def _equity(self) -> float:
        return self.cash + self._gross_exposure()

    def _remaining_exposure_capacity(self) -> float:
        max_exposure = max(self._equity(), 0.0) * self.config.max_gross_exposure_pct
        return max(0.0, max_exposure - self._gross_exposure())

    def _in_cooldown(self, condition_id: str, outcome_index: int, run_at: datetime) -> bool:
        last_exit = self.last_exit_at.get((condition_id, outcome_index))
        if last_exit is None:
            return False
        return (run_at - last_exit).total_seconds() < self.config.cooldown_seconds

    def _build_order(
        self,
        *,
        position_id: str,
        condition_id: str,
        question: str,
        outcome: str,
        outcome_index: int,
        side: str,
        price: float,
        size: float,
        edge: float,
        score: float,
        conviction: float,
        buy_share: float,
        recent_trade_count: int,
        recent_notional: float,
        market_price: float,
        price_gap_pct: float,
        signal_runs: int,
        signal_age_seconds: float,
        signal_persistence_bucket: str,
        kalshi_match_score: float,
        kalshi_match_bucket: str,
        cross_market_support: float,
        cross_market_support_bucket: str,
        cross_market_reason: str,
        reason: str,
        holding_seconds: float = 0.0,
        realized_pnl: float = 0.0,
        unrealized_pnl_after: float = 0.0,
    ) -> Order:
        notional = size * price
        return Order(
            position_id=position_id,
            condition_id=condition_id,
            question=question,
            outcome=outcome,
            outcome_index=outcome_index,
            side=side,
            price=price,
            size=size,
            notional=notional,
            edge=edge,
            score=score,
            conviction=conviction,
            buy_share=buy_share,
            recent_trade_count=recent_trade_count,
            recent_notional=recent_notional,
            market_price=market_price,
            price_gap_pct=price_gap_pct,
            signal_runs=signal_runs,
            signal_age_seconds=signal_age_seconds,
            signal_persistence_bucket=signal_persistence_bucket,
            kalshi_match_score=kalshi_match_score,
            kalshi_match_bucket=kalshi_match_bucket,
            cross_market_support=cross_market_support,
            cross_market_support_bucket=cross_market_support_bucket,
            cross_market_reason=cross_market_reason,
            reason=reason,
            holding_seconds=holding_seconds,
            realized_pnl=realized_pnl,
            unrealized_pnl_after=unrealized_pnl_after,
            cash_after=self.cash,
            gross_exposure_after=self._gross_exposure(),
            equity_after=self._equity(),
        )

    def execute_exits(self, exit_signals: pd.DataFrame, run_at: datetime) -> None:
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
            slippage = _env_float("PAPER_SLIPPAGE_PCT", 0.005)
            # Fetch live bid — when selling on the CLOB you receive the best bid, not midpoint.
            token_id_exit = str(position.get("asset", ""))
            live_bid_exit: float | None = None
            if token_id_exit:
                import httpx as _httpx
                try:
                    _r = _httpx.get(
                        "https://clob.polymarket.com/book",
                        params={"token_id": token_id_exit},
                        timeout=5.0,
                    )
                    if _r.status_code == 200:
                        _bids = _r.json().get("bids", [])
                        if _bids:
                            live_bid_exit = max(float(b.get("price", 0)) for b in _bids)
                except Exception:
                    pass
            # Use live bid if available; fall back to midpoint with slippage.
            if live_bid_exit and live_bid_exit > 0:
                exit_price = max(live_bid_exit * (1 - slippage), 0.01)
            else:
                exit_price = max(float(exit_row["market_price"]) * (1 - slippage), 0.01)
            size = float(position["size"])
            notional = size * exit_price
            realized_pnl = notional - float(position["cost_basis"])

            # If live trading is enabled, place the real sell order first.
            # Only remove the position and update accounting if the sell succeeds.
            if self.live_executor is not None:
                token_id = str(position.get("asset", ""))
                try:
                    self.live_executor.sell(token_id, exit_price, size)
                except Exception as exc:
                    print(f"[LIVE] SELL rejected for '{position.get('question')}': {exc}")
                    remaining_positions.append(position)
                    continue

            self.cash += notional
            self.realized_pnl += realized_pnl
            self.last_exit_at[key] = run_at
            self.orders.append(
                self._build_order(
                    position_id=str(position["position_id"]),
                    condition_id=str(position["condition_id"]),
                    question=str(position["question"]),
                    outcome=str(position["outcome"]),
                    outcome_index=int(position["outcome_index"]),
                    side="sell",
                    price=exit_price,
                    size=size,
                    edge=float(exit_row["edge"]),
                    score=float(exit_row["score"]),
                    conviction=float(position.get("conviction", 0.0)),
                    buy_share=float(exit_row.get("buy_share", 0.0) or 0.0),
                    recent_trade_count=int(exit_row.get("recent_trade_count", 0) or 0),
                    recent_notional=float(exit_row.get("recent_notional", 0.0) or 0.0),
                    market_price=exit_price,
                    price_gap_pct=float(exit_row.get("return_pct", 0.0) or 0.0),
                    signal_runs=int(position.get("signal_runs", 1) or 1),
                    signal_age_seconds=float(position.get("signal_age_seconds", 0.0) or 0.0),
                    signal_persistence_bucket=str(position.get("signal_persistence_bucket", "fresh")),
                    kalshi_match_score=float(exit_row.get("kalshi_match_score", 0.0) or 0.0),
                    kalshi_match_bucket=str(exit_row.get("kalshi_match_bucket", "none")),
                    cross_market_support=float(exit_row.get("cross_market_support", 0.0) or 0.0),
                    cross_market_support_bucket=str(exit_row.get("cross_market_support_bucket", "neutral")),
                    cross_market_reason=str(exit_row.get("cross_market_reason", "")),
                    reason=str(exit_row["exit_reason"]),
                    holding_seconds=float(exit_row.get("holding_seconds", 0.0) or 0.0),
                    realized_pnl=realized_pnl,
                    unrealized_pnl_after=0.0,
                )
            )

        self.positions = remaining_positions

    def execute(self, signals: pd.DataFrame, run_at: datetime) -> None:
        existing = {(position["condition_id"], int(position["outcome_index"])) for position in self.positions}
        # Track which condition_ids already have a position — never hold both Yes and No on the same market.
        existing_markets = {position["condition_id"] for position in self.positions}
        for _, signal in signals.iterrows():
            if len(self.positions) >= self.config.max_positions:
                break
            if self.cash <= 0:
                break

            key = (str(signal["condition_id"]), int(signal["outcome_index"]))
            if key in existing or self._in_cooldown(key[0], key[1], run_at):
                continue
            # Skip if we already hold the other side of this market.
            if str(signal["condition_id"]) in existing_markets:
                continue

            signal_price = float(signal["market_price"])
            if signal_price <= 0:
                continue

            # Fetch the live order book immediately before entry.
            # We need:
            #   1. The actual ask price (what you pay to buy YES) — not the midpoint
            #   2. The spread — if bid/ask gap > max_spread, market is too illiquid to trade
            #   3. Staleness check — if live ask differs from signal price by > max_drift, skip
            token_id_for_price = str(signal.get("asset", ""))
            live_ask: float | None = None
            live_bid: float | None = None
            if token_id_for_price:
                import httpx as _httpx
                try:
                    _resp = _httpx.get(
                        "https://clob.polymarket.com/book",
                        params={"token_id": token_id_for_price},
                        timeout=5.0,
                    )
                    if _resp.status_code == 200:
                        _book = _resp.json()
                        _bids = _book.get("bids", [])
                        _asks = _book.get("asks", [])
                        if _bids:
                            live_bid = max(float(b.get("price", 0)) for b in _bids)
                        if _asks:
                            live_ask = min(float(a.get("price", 0)) for a in _asks)
                except Exception:
                    pass

            max_spread = _env_float("PAPER_MAX_ENTRY_SPREAD", 0.10)   # skip if bid/ask gap > 10%
            max_drift = _env_float("PAPER_MAX_ENTRY_DRIFT", 0.05)     # skip if ask moved > 5% from signal

            if live_ask is not None and live_bid is not None:
                spread = live_ask - live_bid
                if spread > max_spread:
                    print(
                        f"[SKIP SPREAD] {str(signal.get('question',''))[:50]} | "
                        f"bid={live_bid:.4f} ask={live_ask:.4f} spread={spread:.4f}"
                    )
                    continue
                price_drift = abs(live_ask - signal_price) / max(signal_price, 1e-9)
                if price_drift > max_drift:
                    print(
                        f"[SKIP STALE] {str(signal.get('question',''))[:50]} | "
                        f"signal={signal_price:.4f} ask={live_ask:.4f} drift={price_drift:.1%}"
                    )
                    continue
                price = live_ask  # pay the ask — this is what you actually pay on Polymarket
            elif live_ask is not None:
                price_drift = abs(live_ask - signal_price) / max(signal_price, 1e-9)
                if price_drift > max_drift:
                    print(
                        f"[SKIP STALE] {str(signal.get('question',''))[:50]} | "
                        f"signal={signal_price:.4f} ask={live_ask:.4f} drift={price_drift:.1%}"
                    )
                    continue
                price = live_ask
            else:
                # Could not get a live order book — market is likely illiquid or API failed.
                # Never enter on a stale signal price with no live confirmation.
                print(
                    f"[SKIP NO BOOK] {str(signal.get('question',''))[:50]} | "
                    f"signal={signal_price:.4f} — no live order book"
                )
                continue

            # Simulate slippage: pay slightly more than the quoted price on entry.
            slippage = _env_float("PAPER_SLIPPAGE_PCT", 0.005)
            price = min(price * (1 + slippage), 0.99)

            remaining_exposure = self._remaining_exposure_capacity()
            if remaining_exposure < self.config.min_position_dollars:
                break

            conviction = float(signal.get("conviction", 0.0))
            target_notional = self.config.min_position_dollars + conviction * (
                self.config.max_position_dollars - self.config.min_position_dollars
            )
            notional = min(target_notional, self.cash, remaining_exposure)
            if notional < self.config.min_position_dollars:
                continue

            size = notional / price
            token_id = str(signal.get("asset", ""))

            # If live trading is enabled, place the real order first.
            # Only proceed with paper accounting if the live order succeeds.
            live_order_id = ""
            if self.live_executor is not None:
                try:
                    result = self.live_executor.buy(token_id, price, notional)
                    live_order_id = result.get("orderID") or result.get("id") or ""
                except Exception as exc:
                    print(f"[LIVE] BUY rejected for '{signal.get('question')}': {exc}")
                    continue

            self.cash -= notional
            existing_markets.add(str(signal["condition_id"]))
            position_id = f"{signal['condition_id']}:{int(signal['outcome_index'])}:{run_at.isoformat()}"
            self.positions.append(
                {
                    "position_id": position_id,
                    "condition_id": str(signal["condition_id"]),
                    "question": str(signal["question"]),
                    "outcome": str(signal["outcome"]),
                    "outcome_index": int(signal["outcome_index"]),
                    "asset": token_id,
                    "live_order_id": live_order_id,
                    "entry_price": price,
                    "current_price": price,
                    "size": size,
                    "cost_basis": notional,
                    "mark_value": size * price,
                    "unrealized_pnl": 0.0,
                    "edge": float(signal["edge"]),
                    "score": float(signal["score"]),
                    "conviction": conviction,
                    "signal_runs": int(signal.get("signal_runs", 1) or 1),
                    "signal_age_seconds": float(signal.get("signal_age_seconds", 0.0) or 0.0),
                    "signal_persistence_bucket": str(signal.get("signal_persistence_bucket", "fresh")),
                    "peak_price": price,
                    "max_unrealized_pnl": 0.0,
                    "opened_at": run_at.isoformat(),
                    "last_updated_at": run_at.isoformat(),
                }
            )
            self.orders.append(
                self._build_order(
                    position_id=position_id,
                    condition_id=str(signal["condition_id"]),
                    question=str(signal["question"]),
                    outcome=str(signal["outcome"]),
                    outcome_index=int(signal["outcome_index"]),
                    side="buy",
                    price=price,
                    size=size,
                    edge=float(signal["edge"]),
                    score=float(signal["score"]),
                    conviction=conviction,
                    buy_share=float(signal.get("buy_share", 0.0) or 0.0),
                    recent_trade_count=int(signal.get("recent_trade_count", 0) or 0),
                    recent_notional=float(signal.get("recent_notional", 0.0) or 0.0),
                    market_price=price,
                    price_gap_pct=float(signal.get("edge_ratio", 0.0) or 0.0),
                    signal_runs=int(signal.get("signal_runs", 1) or 1),
                    signal_age_seconds=float(signal.get("signal_age_seconds", 0.0) or 0.0),
                    signal_persistence_bucket=str(signal.get("signal_persistence_bucket", "fresh")),
                    kalshi_match_score=float(signal.get("kalshi_match_score", 0.0) or 0.0),
                    kalshi_match_bucket=str(signal.get("kalshi_match_bucket", "none")),
                    cross_market_support=float(signal.get("cross_market_support", 0.0) or 0.0),
                    cross_market_support_bucket=str(signal.get("cross_market_support_bucket", "neutral")),
                    cross_market_reason=str(signal.get("cross_market_reason", "")),
                    reason=str(signal.get("entry_reason", "entry_signal")),
                    unrealized_pnl_after=0.0,
                )
            )
            existing.add(key)

    def orders_frame(self) -> pd.DataFrame:
        columns = [
            "position_id",
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
            "conviction",
            "buy_share",
            "recent_trade_count",
            "recent_notional",
            "market_price",
            "price_gap_pct",
            "signal_runs",
            "signal_age_seconds",
            "signal_persistence_bucket",
            "kalshi_match_score",
            "kalshi_match_bucket",
            "cross_market_support",
            "cross_market_support_bucket",
            "cross_market_reason",
            "reason",
            "holding_seconds",
            "realized_pnl",
            "unrealized_pnl_after",
            "cash_after",
            "gross_exposure_after",
            "equity_after",
        ]
        if not self.orders:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([asdict(order) for order in self.orders], columns=columns)

    def positions_frame(self) -> pd.DataFrame:
        columns = [
            "position_id",
            "condition_id",
            "question",
            "outcome",
            "outcome_index",
            "asset",
            "live_order_id",
            "entry_price",
            "current_price",
            "size",
            "cost_basis",
            "mark_value",
            "unrealized_pnl",
            "edge",
            "score",
            "conviction",
            "signal_runs",
            "signal_age_seconds",
            "signal_persistence_bucket",
            "peak_price",
            "max_unrealized_pnl",
            "opened_at",
            "last_updated_at",
        ]
        if not self.positions:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(self.positions, columns=columns)

    def summary(self) -> dict[str, float | int]:
        unrealized_pnl = sum(float(position.get("unrealized_pnl", 0.0)) for position in self.positions)
        return {
            "starting_cash": self.config.starting_cash,
            "cash": self.cash,
            "positions": len(self.positions),
            "orders": len(self.orders),
            "gross_exposure": self._gross_exposure(),
            "equity": self._equity(),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": self.realized_pnl + unrealized_pnl,
        }


class PriceMonitor:
    """Background WebSocket thread that maintains a live mid-price cache for open positions.

    Subscribes to ``wss://ws-subscriptions-clob.polymarket.com/ws/market`` and updates
    an in-memory dict whenever the CLOB pushes a ``price_change``, ``last_trade_price``,
    or ``book`` event.  A REST ``POST /midpoints`` fallback seeds the cache for tokens
    that haven't received a WS message yet.

    Usage::

        monitor = PriceMonitor()
        monitor.start()
        monitor.subscribe(["token_id_1", "token_id_2"])
        price = monitor.get_price("token_id_1")   # None until first update
        monitor.stop()
    """

    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    CLOB_REST = "https://clob.polymarket.com"

    def __init__(self) -> None:
        self._prices: dict[str, float] = {}
        self._last_trade_prices: dict[str, float] = {}  # only actual trade executions
        self._lock = threading.Lock()
        self._subscribed: set[str] = set()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None  # websockets connection, set inside the async loop
        self._running = False

    # ------------------------------------------------------------------
    # Public API (called from the main thread)
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="price-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        # Close the WebSocket gracefully so the async loop exits on its own.
        if self._loop and self._ws is not None:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)
        elif self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def get_price(self, token_id: str) -> float | None:
        with self._lock:
            return self._prices.get(token_id)

    def subscribe(self, token_ids: list[str]) -> None:
        """Add token IDs to the subscription set.  Safe to call from any thread."""
        new_ids = [t for t in token_ids if t and t not in self._subscribed]
        if not new_ids:
            return
        self._subscribed.update(new_ids)
        # Seed cache via REST immediately so we don't wait for the first WS message.
        self._seed_rest(new_ids)
        # If WS is connected, dynamically subscribe without reconnecting.
        if self._loop and self._ws is not None:
            msg = json.dumps({"assets_ids": new_ids, "operation": "subscribe"})
            asyncio.run_coroutine_threadsafe(self._send(msg), self._loop)

    def unsubscribe(self, token_ids: list[str]) -> None:
        for t in token_ids:
            self._subscribed.discard(t)
            with self._lock:
                self._prices.pop(t, None)
        if self._loop and self._ws is not None and token_ids:
            msg = json.dumps({"assets_ids": token_ids, "operation": "unsubscribe"})
            asyncio.run_coroutine_threadsafe(self._send(msg), self._loop)

    # ------------------------------------------------------------------
    # REST seed (called from main thread when subscribing)
    # ------------------------------------------------------------------

    def _seed_rest(self, token_ids: list[str]) -> None:
        """Fetch midpoints via REST and populate cache so prices are available immediately."""
        import httpx
        try:
            resp = httpx.post(
                f"{self.CLOB_REST}/midpoints",
                json=[{"token_id": t} for t in token_ids],
                timeout=8.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Response may be a list or a dict keyed by token_id.
                items = data if isinstance(data, list) else [{"token_id": k, "mid": v} for k, v in data.items()]
                with self._lock:
                    for item in items:
                        tid = item.get("token_id") or item.get("asset_id")
                        mid = item.get("mid") or item.get("price")
                        if tid and mid is not None:
                            try:
                                self._prices[str(tid)] = float(mid)
                            except (TypeError, ValueError):
                                pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Background async loop (runs in daemon thread)
    # ------------------------------------------------------------------

    def _run(self) -> None:
        # Windows ProactorEventLoop has GIL issues in background threads.
        # SelectorEventLoop works reliably on all platforms.
        import sys
        if sys.platform == "win32":
            self._loop = asyncio.SelectorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._listen())
        except Exception:
            pass

    async def _send(self, msg: str) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(msg)
            except Exception:
                pass

    async def _ping_loop(self, ws: Any) -> None:
        # Send first PING immediately — server drops idle connections after ~10s.
        try:
            await ws.send("PING")
        except Exception:
            return
        while True:
            await asyncio.sleep(9)
            try:
                await ws.send("PING")
            except Exception:
                break

    async def _listen(self) -> None:
        import websockets

        while self._running:
            try:
                async with websockets.connect(self.WS_URL, ping_interval=None, open_timeout=15) as ws:
                    self._ws = ws
                    print("[PRICE MONITOR] WebSocket connected")

                    # Subscribe to known tokens, or send a minimal keepalive subscription
                    # so the server doesn't close an idle connection immediately.
                    sub_ids = list(self._subscribed) if self._subscribed else []
                    await ws.send(json.dumps({
                        "assets_ids": sub_ids,
                        "type": "market",
                        "custom_feature_enabled": True,
                    }))

                    ping_task = asyncio.create_task(self._ping_loop(ws))
                    try:
                        async for raw in ws:
                            if not self._running:
                                break
                            if raw == "PONG":
                                continue
                            try:
                                data = json.loads(raw)
                            except Exception:
                                continue
                            # Server sometimes sends a list of messages in one frame.
                            # Wrap each call so one bad message never kills the connection.
                            try:
                                if isinstance(data, list):
                                    for item in data:
                                        if isinstance(item, dict):
                                            try:
                                                self._handle_message(item)
                                            except Exception:
                                                pass
                                elif isinstance(data, dict):
                                    self._handle_message(data)
                            except Exception:
                                pass
                    finally:
                        ping_task.cancel()
            except Exception as exc:
                if self._running:
                    import traceback as _tb
                    print(f"[PRICE MONITOR] WS error: {exc}")
                    _tb.print_exc()
                    print("[PRICE MONITOR] Reconnecting in 5s...")
                    await asyncio.sleep(5)
            finally:
                self._ws = None

    def _handle_message(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        event_type = data.get("event_type")

        # Maximum spread we trust for price updates from book/price_change events.
        # Wide-spread books (illiquid markets) produce unreliable midpoints.
        # last_trade_price is always trustworthy — it reflects an actual execution.
        MAX_TRUSTED_SPREAD = 0.10

        if event_type == "last_trade_price":
            # Actual trade execution — highest quality price signal, always trust it.
            asset_id = str(data.get("asset_id", ""))
            price = data.get("price")
            if asset_id and price is not None:
                try:
                    with self._lock:
                        self._prices[asset_id] = float(price)
                        self._last_trade_prices[asset_id] = float(price)
                except (TypeError, ValueError):
                    pass

        elif event_type == "price_change":
            for change in data.get("price_changes", []):
                asset_id = str(change.get("asset_id", ""))
                best_bid = change.get("best_bid")
                best_ask = change.get("best_ask")
                if asset_id and best_bid is not None and best_ask is not None:
                    try:
                        bid_f = float(best_bid)
                        ask_f = float(best_ask)
                        spread = ask_f - bid_f
                        if spread <= MAX_TRUSTED_SPREAD:
                            mid = (bid_f + ask_f) / 2.0
                            with self._lock:
                                self._prices[asset_id] = mid
                        # If spread is wide, only update if we have no last_trade_price yet
                        else:
                            with self._lock:
                                if asset_id not in self._last_trade_prices:
                                    mid = (bid_f + ask_f) / 2.0
                                    self._prices[asset_id] = mid
                    except (TypeError, ValueError):
                        pass

        elif event_type == "book":
            asset_id = str(data.get("asset_id", ""))
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            if asset_id and bids and asks:
                try:
                    bid_f = max(float(b["price"]) for b in bids)
                    ask_f = min(float(a["price"]) for a in asks)
                    spread = ask_f - bid_f
                    if spread <= MAX_TRUSTED_SPREAD:
                        mid = (bid_f + ask_f) / 2.0
                        with self._lock:
                            self._prices[asset_id] = mid
                    else:
                        with self._lock:
                            if asset_id not in self._last_trade_prices:
                                mid = (bid_f + ask_f) / 2.0
                                self._prices[asset_id] = mid
                except (TypeError, ValueError, KeyError, IndexError):
                    pass


class PaperTradingBot:
    def __init__(
        self,
        data_dir: Path | str = "data/current/polymarket",
        kalshi_data_dir: Path | str = "data/current/kalshi",
        output_dir: Path | str = "output/paper_trading/polymarket",
        strategy: VolumeMomentumStrategy | None = None,
        portfolio: PaperPortfolio | None = None,
        live_executor: LiveExecutor | None = None,
    ):
        self.snapshot = PolymarketSnapshot(data_dir=data_dir)
        self.kalshi_snapshot = KalshiSnapshot(data_dir=kalshi_data_dir)
        self.output_dir = Path(output_dir)
        self.strategy = strategy or VolumeMomentumStrategy()
        self.portfolio = portfolio or PaperPortfolio(live_executor=live_executor)
        self.price_monitor = PriceMonitor()
        self._last_positions_write: float = 0.0  # unix timestamp of last positions.csv write

    def subscribe_open_positions(self) -> None:
        """Subscribe the price monitor to all currently open position token IDs."""
        token_ids = [str(p.get("asset", "")) for p in self.portfolio.positions if p.get("asset")]
        if token_ids:
            self.price_monitor.subscribe(token_ids)

    def _load_signal_history(self) -> pd.DataFrame:
        history_path = self.output_dir / "signal_history.csv"
        columns = [
            "condition_id",
            "outcome_index",
            "first_seen_at",
            "last_seen_at",
            "signal_runs",
            "signal_age_seconds",
            "signal_persistence_bucket",
            "last_conviction",
            "last_cross_market_support",
        ]
        if not history_path.exists():
            return pd.DataFrame(columns=columns)
        history = pd.read_csv(history_path)
        return history.reindex(columns=columns)

    def _apply_signal_history(self, outcome_df: pd.DataFrame, run_at: datetime) -> pd.DataFrame:
        if outcome_df.empty:
            return outcome_df
        history = self._load_signal_history()
        if history.empty:
            enriched = outcome_df.copy()
            enriched["signal_runs"] = 1
            enriched["signal_age_seconds"] = 0.0
            enriched["signal_persistence_bucket"] = "fresh"
            return enriched

        merged = outcome_df.merge(history, on=["condition_id", "outcome_index"], how="left")
        merged["first_seen_at"] = pd.to_datetime(merged["first_seen_at"], utc=True, errors="coerce")
        merged["last_seen_at"] = pd.to_datetime(merged["last_seen_at"], utc=True, errors="coerce")
        previous_age = (pd.Timestamp(run_at) - merged["first_seen_at"]).dt.total_seconds()
        merged["signal_runs"] = merged["signal_runs"].fillna(1)
        merged.loc[merged["first_seen_at"].isna(), "signal_runs"] = 1
        merged["signal_age_seconds"] = previous_age.fillna(0.0)
        merged["signal_persistence_bucket"] = merged.apply(
            lambda row: _persistence_bucket(int(row["signal_runs"]), float(row["signal_age_seconds"])), axis=1
        )
        return merged

    def _write_signal_history(self, scored_df: pd.DataFrame, run_at: datetime) -> Path:
        history_path = self.output_dir / "signal_history.csv"
        columns = [
            "condition_id",
            "outcome_index",
            "first_seen_at",
            "last_seen_at",
            "signal_runs",
            "signal_age_seconds",
            "signal_persistence_bucket",
            "last_conviction",
            "last_cross_market_support",
        ]
        prior = self._load_signal_history()
        prior_map: dict[tuple[str, int], dict[str, Any]] = {}
        if not prior.empty:
            prior_map = {(str(row["condition_id"]), int(row["outcome_index"])): row for _, row in prior.iterrows()}

        records: list[dict[str, Any]] = []
        buy_signals = (
            scored_df[scored_df["signal"] == "buy"].copy() if "signal" in scored_df.columns else pd.DataFrame()
        )
        # Carry forward history for markets that briefly drop off the buy list (missed 1-2 cycles).
        # Without this, a market that misses one cycle resets to signal_runs=1 and loses conviction.
        cycle_seconds = 900  # 15-minute cycle
        for _, row in buy_signals.iterrows():
            key = (str(row["condition_id"]), int(row["outcome_index"]))
            previous = prior_map.get(key)
            first_seen_at = pd.Timestamp(run_at)
            signal_runs = 1
            if previous is not None and pd.notna(previous.get("first_seen_at")):
                first_seen_at = pd.to_datetime(previous["first_seen_at"], utc=True, errors="coerce")
                if pd.isna(first_seen_at):
                    first_seen_at = pd.Timestamp(run_at)
                prev_last_seen = pd.to_datetime(previous.get("last_seen_at"), utc=True, errors="coerce")
                # If the signal was last seen within 3 cycles, treat as continuous (not reset).
                if pd.notna(prev_last_seen) and (pd.Timestamp(run_at) - prev_last_seen).total_seconds() <= cycle_seconds * 3:
                    signal_runs = int(previous.get("signal_runs", 0) or 0) + 1
                else:
                    # Gap too large — start fresh but keep first_seen_at for age tracking
                    signal_runs = 1
            signal_age_seconds = max((pd.Timestamp(run_at) - first_seen_at).total_seconds(), 0.0)
            records.append(
                {
                    "condition_id": key[0],
                    "outcome_index": key[1],
                    "first_seen_at": first_seen_at.isoformat(),
                    "last_seen_at": pd.Timestamp(run_at).isoformat(),
                    "signal_runs": signal_runs,
                    "signal_age_seconds": signal_age_seconds,
                    "signal_persistence_bucket": _persistence_bucket(signal_runs, signal_age_seconds),
                    "last_conviction": float(row.get("conviction", 0.0) or 0.0),
                    "last_cross_market_support": float(row.get("cross_market_support", 0.0) or 0.0),
                }
            )

        pd.DataFrame(records, columns=columns).to_csv(history_path, index=False)
        return history_path

    def _append_ledger(self, orders_df: pd.DataFrame, run_at: datetime) -> Path:
        ledger_path = self.output_dir / "ledger.csv"
        columns = [
            "run_at",
            "position_id",
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
            "conviction",
            "buy_share",
            "recent_trade_count",
            "recent_notional",
            "market_price",
            "price_gap_pct",
            "signal_runs",
            "signal_age_seconds",
            "signal_persistence_bucket",
            "kalshi_match_score",
            "kalshi_match_bucket",
            "cross_market_support",
            "cross_market_support_bucket",
            "cross_market_reason",
            "reason",
            "holding_seconds",
            "realized_pnl",
            "unrealized_pnl_after",
            "cash_after",
            "gross_exposure_after",
            "equity_after",
        ]
        if orders_df.empty:
            if ledger_path.exists():
                existing = pd.read_csv(ledger_path)
                if list(existing.columns) != columns:
                    existing = existing.reindex(columns=columns)
                    existing.to_csv(ledger_path, index=False)
            else:
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

    def _write_closed_trades(self, ledger_df: pd.DataFrame) -> Path:
        closed_trades_path = self.output_dir / "closed_trades.csv"
        columns = [
            "position_id",
            "condition_id",
            "question",
            "outcome",
            "outcome_index",
            "entry_run_at",
            "exit_run_at",
            "entry_price",
            "exit_price",
            "size",
            "entry_notional",
            "exit_notional",
            "holding_seconds",
            "realized_pnl",
            "return_pct",
            "signal_runs",
            "entry_timing_bucket",
            "signal_age_seconds",
            "signal_persistence_bucket",
            "kalshi_match_score",
            "kalshi_match_bucket",
            "cross_market_support",
            "cross_market_support_bucket",
            "cross_market_reason",
            "entry_reason",
            "exit_reason",
        ]
        if ledger_df.empty:
            pd.DataFrame(columns=columns).to_csv(closed_trades_path, index=False)
            return closed_trades_path

        buys = ledger_df[ledger_df["side"] == "buy"].copy()
        sells = ledger_df[ledger_df["side"] == "sell"].copy()
        if buys.empty or sells.empty:
            pd.DataFrame(columns=columns).to_csv(closed_trades_path, index=False)
            return closed_trades_path

        closed = buys.merge(sells, on="position_id", suffixes=("_entry", "_exit"), how="inner")
        if closed.empty:
            pd.DataFrame(columns=columns).to_csv(closed_trades_path, index=False)
            return closed_trades_path

        report = pd.DataFrame(
            {
                "position_id": closed["position_id"],
                "condition_id": closed["condition_id_entry"],
                "question": closed["question_entry"],
                "outcome": closed["outcome_entry"],
                "outcome_index": closed["outcome_index_entry"],
                "entry_run_at": closed["run_at_entry"],
                "exit_run_at": closed["run_at_exit"],
                "entry_price": closed["price_entry"],
                "exit_price": closed["price_exit"],
                "size": closed["size_entry"],
                "entry_notional": closed["notional_entry"],
                "exit_notional": closed["notional_exit"],
                "holding_seconds": closed["holding_seconds_exit"],
                "realized_pnl": closed["realized_pnl_exit"],
                "return_pct": closed["realized_pnl_exit"] / closed["notional_entry"].clip(lower=1e-9),
                "signal_runs": closed["signal_runs_entry"],
                "entry_timing_bucket": closed["signal_runs_entry"].apply(
                    lambda value: _entry_timing_bucket(int(value))
                ),
                "signal_age_seconds": closed["signal_age_seconds_entry"],
                "signal_persistence_bucket": closed["signal_persistence_bucket_entry"],
                "kalshi_match_score": closed["kalshi_match_score_entry"],
                "kalshi_match_bucket": closed["kalshi_match_bucket_entry"],
                "cross_market_support": closed["cross_market_support_entry"],
                "cross_market_support_bucket": closed["cross_market_support_bucket_entry"],
                "cross_market_reason": closed["cross_market_reason_entry"],
                "entry_reason": closed["reason_entry"],
                "exit_reason": closed["reason_exit"],
            }
        ).sort_values("exit_run_at")
        report.to_csv(closed_trades_path, index=False)
        return closed_trades_path

    def _write_performance_breakdown(self, closed_df: pd.DataFrame) -> Path:
        breakdown_path = self.output_dir / "performance_breakdown.json"
        if closed_df.empty:
            breakdown_path.write_text(
                json.dumps(
                    {
                        "by_support_bucket": {},
                        "by_match_bucket": {},
                        "by_persistence_bucket": {},
                        "by_entry_timing_bucket": {},
                    },
                    indent=2,
                )
                + "\n"
            )
            return breakdown_path

        def _group_stats(frame: pd.DataFrame, column: str) -> dict[str, dict[str, float | int]]:
            result: dict[str, dict[str, float | int]] = {}
            for bucket, bucket_df in frame.groupby(column, dropna=False):
                key = str(bucket)
                result[key] = {
                    "trades": int(len(bucket_df)),
                    "wins": int((bucket_df["realized_pnl"] > 0).sum()),
                    "losses": int((bucket_df["realized_pnl"] < 0).sum()),
                    "win_rate": float((bucket_df["realized_pnl"] > 0).mean()),
                    "avg_realized_pnl": float(bucket_df["realized_pnl"].mean()),
                    "avg_return_pct": float(bucket_df["return_pct"].mean()),
                }
            return result

        payload = {
            "by_support_bucket": _group_stats(closed_df, "cross_market_support_bucket"),
            "by_match_bucket": _group_stats(closed_df, "kalshi_match_bucket"),
            "by_persistence_bucket": _group_stats(closed_df, "signal_persistence_bucket"),
            "by_entry_timing_bucket": _group_stats(closed_df, "entry_timing_bucket"),
        }
        breakdown_path.write_text(json.dumps(payload, indent=2) + "\n")
        return breakdown_path

    def _performance_report(
        self, ledger_df: pd.DataFrame, positions_df: pd.DataFrame, summary: dict[str, float | int]
    ) -> dict[str, float | int]:
        closed_trades_path = self.output_dir / "closed_trades.csv"
        closed_df = pd.read_csv(closed_trades_path) if closed_trades_path.exists() else pd.DataFrame()

        wins = 0
        losses = 0
        win_rate = 0.0
        avg_realized_pnl = 0.0
        kalshi_confirmed_trades = 0
        kalshi_confirmed_win_rate = 0.0
        kalshi_confirmed_avg_realized_pnl = 0.0
        unconfirmed_closed_trades = 0
        unconfirmed_avg_realized_pnl = 0.0
        first_entry_avg_realized_pnl = 0.0
        later_entry_avg_realized_pnl = 0.0
        if not closed_df.empty:
            wins = int((closed_df["realized_pnl"] > 0).sum())
            losses = int((closed_df["realized_pnl"] < 0).sum())
            win_rate = wins / len(closed_df)
            avg_realized_pnl = float(closed_df["realized_pnl"].mean())
            kalshi_confirmed_trades = int((closed_df["cross_market_support"] > 0).sum())
            confirmed_df = closed_df[closed_df["cross_market_support"] > 0]
            if not confirmed_df.empty:
                kalshi_confirmed_win_rate = float((confirmed_df["realized_pnl"] > 0).mean())
                kalshi_confirmed_avg_realized_pnl = float(confirmed_df["realized_pnl"].mean())
            unconfirmed_df = closed_df[closed_df["cross_market_support"] <= 0]
            unconfirmed_closed_trades = int(len(unconfirmed_df))
            if not unconfirmed_df.empty:
                unconfirmed_avg_realized_pnl = float(unconfirmed_df["realized_pnl"].mean())
            first_entry_df = closed_df[closed_df["entry_timing_bucket"] == "first_entry"]
            if not first_entry_df.empty:
                first_entry_avg_realized_pnl = float(first_entry_df["realized_pnl"].mean())
            later_entry_df = closed_df[closed_df["entry_timing_bucket"] != "first_entry"]
            if not later_entry_df.empty:
                later_entry_avg_realized_pnl = float(later_entry_df["realized_pnl"].mean())

        return {
            **summary,
            "open_positions": int(len(positions_df)),
            "closed_trades": int(len(closed_df)),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "avg_realized_pnl": avg_realized_pnl,
            "kalshi_confirmed_trades": kalshi_confirmed_trades,
            "kalshi_confirmed_win_rate": kalshi_confirmed_win_rate,
            "kalshi_confirmed_avg_realized_pnl": kalshi_confirmed_avg_realized_pnl,
            "unconfirmed_closed_trades": unconfirmed_closed_trades,
            "unconfirmed_avg_realized_pnl": unconfirmed_avg_realized_pnl,
            "first_entry_avg_realized_pnl": first_entry_avg_realized_pnl,
            "later_entry_avg_realized_pnl": later_entry_avg_realized_pnl,
            "ledger_rows": int(len(ledger_df)),
        }

    def fast_exit_check(self) -> None:
        """Check open-position prices and exit on stop-loss / take-profit / trailing-stop.

        Prices come from the live WebSocket cache (sub-second latency).  Any tokens not yet
        in the cache fall back to a single batched REST ``POST /midpoints`` call.
        Called every ~1 second between full cycles — does NOT enter new positions.
        """
        if not self.portfolio.positions:
            return

        run_at = datetime.now(timezone.utc)
        cfg = self.strategy.config
        slippage = _env_float("PAPER_SLIPPAGE_PCT", 0.005)

        # --- Collect prices: WS cache first, REST batch fallback for misses ---
        prices: dict[str, float] = {}
        missing: list[str] = []
        for position in self.portfolio.positions:
            token_id = str(position.get("asset", ""))
            if not token_id:
                continue
            cached = self.price_monitor.get_price(token_id)
            if cached is not None:
                prices[token_id] = cached
            else:
                missing.append(token_id)

        if missing:
            import httpx
            try:
                resp = httpx.post(
                    "https://clob.polymarket.com/midpoints",
                    json=[{"token_id": t} for t in missing],
                    timeout=8.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data if isinstance(data, list) else [{"token_id": k, "mid": v} for k, v in data.items()]
                    for item in items:
                        tid = str(item.get("token_id") or item.get("asset_id") or "")
                        mid = item.get("mid") or item.get("price")
                        if tid and mid is not None:
                            try:
                                prices[tid] = float(mid)
                            except (TypeError, ValueError):
                                pass
            except Exception:
                pass

        if not prices:
            return

        # --- Update mark-to-market and determine exits ---
        exits: list[tuple[dict, str, float]] = []  # (position, reason, current_price)
        for position in self.portfolio.positions:
            token_id = str(position.get("asset", ""))
            if token_id not in prices:
                continue
            current_price = prices[token_id]
            entry_price = float(position["entry_price"])
            peak_price = float(position.get("peak_price", entry_price))
            new_peak = max(peak_price, current_price)

            position["current_price"] = current_price
            position["peak_price"] = new_peak
            position["mark_value"] = float(position["size"]) * current_price
            position["unrealized_pnl"] = position["mark_value"] - float(position["cost_basis"])
            position["last_updated_at"] = run_at.isoformat()

            return_pct = (current_price - entry_price) / max(entry_price, 1e-9)
            drawdown_pct = (current_price - new_peak) / max(new_peak, 1e-9)

            exit_reason: str | None = None
            if return_pct <= -cfg.stop_loss_pct:
                exit_reason = "stop_loss"
            elif return_pct >= cfg.take_profit_pct:
                exit_reason = "take_profit"
            elif return_pct > 0 and drawdown_pct <= -cfg.trailing_stop_drawdown_pct:
                exit_reason = "trailing_stop"

            if exit_reason:
                exits.append((position, exit_reason, current_price))

        # Write positions.csv at most every 30s (keeps dashboard fresh without hammering disk).
        now_ts = time.time()
        if exits or (now_ts - self._last_positions_write >= 30):
            self.portfolio.positions_frame().to_csv(self.output_dir / "positions.csv", index=False)
            self._last_positions_write = now_ts

        if not exits:
            return

        # --- Execute exits ---
        starting_order_count = len(self.portfolio.orders)
        for position, exit_reason, current_price in exits:
            # Fetch live bid — selling on the CLOB means hitting the best bid, not the midpoint.
            token_id_exit = str(position.get("asset", ""))
            live_bid_exit: float | None = None
            if token_id_exit:
                import httpx as _httpx
                try:
                    _r = _httpx.get(
                        "https://clob.polymarket.com/book",
                        params={"token_id": token_id_exit},
                        timeout=5.0,
                    )
                    if _r.status_code == 200:
                        _bids = _r.json().get("bids", [])
                        if _bids:
                            live_bid_exit = max(float(b.get("price", 0)) for b in _bids)
                except Exception:
                    pass
            if live_bid_exit and live_bid_exit > 0:
                exit_price = max(live_bid_exit * (1 - slippage), 0.01)
            else:
                exit_price = max(current_price * (1 - slippage), 0.01)
            size = float(position["size"])
            notional = size * exit_price
            realized_pnl = notional - float(position["cost_basis"])
            key = (str(position["condition_id"]), int(position["outcome_index"]))
            try:
                opened_at = datetime.fromisoformat(str(position["opened_at"]).replace("Z", "+00:00"))
                holding_seconds = (run_at - opened_at).total_seconds()
            except Exception:
                holding_seconds = 0.0

            self.portfolio.cash += notional
            self.portfolio.realized_pnl += realized_pnl
            self.portfolio.last_exit_at[key] = run_at
            self.portfolio.orders.append(
                self.portfolio._build_order(
                    position_id=str(position["position_id"]),
                    condition_id=str(position["condition_id"]),
                    question=str(position["question"]),
                    outcome=str(position["outcome"]),
                    outcome_index=int(position["outcome_index"]),
                    side="sell",
                    price=exit_price,
                    size=size,
                    edge=0.0,
                    score=0.0,
                    conviction=float(position.get("conviction", 0.0)),
                    buy_share=0.0,
                    recent_trade_count=0,
                    recent_notional=0.0,
                    market_price=exit_price,
                    price_gap_pct=(exit_price - float(position["entry_price"])) / max(float(position["entry_price"]), 1e-9),
                    signal_runs=int(position.get("signal_runs", 1) or 1),
                    signal_age_seconds=float(position.get("signal_age_seconds", 0.0) or 0.0),
                    signal_persistence_bucket=str(position.get("signal_persistence_bucket", "fresh")),
                    kalshi_match_score=0.0,
                    kalshi_match_bucket="none",
                    cross_market_support=0.0,
                    cross_market_support_bucket="neutral",
                    cross_market_reason="",
                    reason=exit_reason,
                    holding_seconds=holding_seconds,
                    realized_pnl=realized_pnl,
                    unrealized_pnl_after=0.0,
                )
            )
            self.portfolio.positions.remove(position)
            print(
                f"[FAST EXIT] {exit_reason} | {str(position['question'])[:60]} | "
                f"entry={float(position['entry_price']):.4f} exit={exit_price:.4f} pnl=${realized_pnl:.2f}"
            )

        # --- Persist state after exits ---
        positions_df = self.portfolio.positions_frame()
        positions_df.to_csv(self.output_dir / "positions.csv", index=False)
        orders_df = self.portfolio.orders_frame()
        orders_df.to_csv(self.output_dir / "orders.csv", index=False)
        new_orders_df = orders_df.iloc[starting_order_count:].reset_index(drop=True)
        ledger_path = self._append_ledger(new_orders_df, run_at)
        ledger_df = pd.read_csv(ledger_path)
        closed_trades_path = self._write_closed_trades(ledger_df)
        closed_df = pd.read_csv(closed_trades_path) if closed_trades_path.exists() else pd.DataFrame()
        self._write_performance_breakdown(closed_df)
        summary = self._performance_report(ledger_df, positions_df, self.portfolio.summary())
        (self.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    def run_once(self) -> dict[str, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        run_at = datetime.now(timezone.utc)

        outcome_df = self.snapshot.outcome_frame()
        latest_ts = pd.to_datetime(outcome_df.get("last_trade_at"), utc=True, errors="coerce").max()
        if pd.isna(latest_ts):
            latest_ts = pd.Timestamp(run_at)
        kalshi_df = self.kalshi_snapshot.signal_frame(latest_ts)
        outcome_df = _merge_cross_market_data(outcome_df, kalshi_df, self.strategy.config, latest_ts)
        outcome_df = self._apply_signal_history(outcome_df, run_at)
        scored = self.strategy.score(outcome_df)
        self.portfolio.load_state(self.output_dir)
        self.portfolio.mark_to_market(scored, run_at)
        starting_order_count = len(self.portfolio.orders)

        exit_signals = self.strategy.generate_exit_signals(self.portfolio.positions_frame(), scored, run_at)
        self.portfolio.execute_exits(exit_signals, run_at)

        orders = self.strategy.generate_signals(scored)
        self.portfolio.execute(orders, run_at)
        self.portfolio.mark_to_market(scored, run_at)

        signals_path = self.output_dir / "signals.csv"
        orders_path = self.output_dir / "orders.csv"
        positions_path = self.output_dir / "positions.csv"
        signal_history_path = self.output_dir / "signal_history.csv"
        summary_path = self.output_dir / "summary.json"
        exits_path = self.output_dir / "exits.csv"
        exit_columns = [
            "position_id",
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
            "holding_seconds",
            "drawdown_from_peak_pct",
            "exit_reason",
        ]

        scored.to_csv(signals_path, index=False)
        orders_df = self.portfolio.orders_frame()
        orders_df.to_csv(orders_path, index=False)
        new_orders_df = orders_df.iloc[starting_order_count:].reset_index(drop=True)
        positions_df = self.portfolio.positions_frame()
        positions_df.to_csv(positions_path, index=False)
        if exit_signals.empty:
            pd.DataFrame(columns=exit_columns).to_csv(exits_path, index=False)
        else:
            exit_signals.to_csv(exits_path, index=False)

        ledger_path = self._append_ledger(new_orders_df, run_at)
        ledger_df = pd.read_csv(ledger_path)
        signal_history_path = self._write_signal_history(scored, run_at)
        closed_trades_path = self._write_closed_trades(ledger_df)
        closed_df = pd.read_csv(closed_trades_path) if closed_trades_path.exists() else pd.DataFrame()
        performance_breakdown_path = self._write_performance_breakdown(closed_df)
        summary = self._performance_report(ledger_df, positions_df, self.portfolio.summary())
        summary_path.write_text(json.dumps(summary, indent=2) + "\n")

        # Print a concise status line each cycle so the user can monitor progress.
        new_signals = int((scored.get("signal", pd.Series()) == "buy").sum()) if "signal" in scored.columns else 0
        top_momentum = scored["price_momentum"].max() if "price_momentum" in scored.columns else 0.0
        print(
            f"  equity=${summary['equity']:.2f} | "
            f"open={summary['open_positions']} | "
            f"closed={summary['closed_trades']} ({summary['wins']}W/{summary['losses']}L) | "
            f"realized=${summary['realized_pnl']:.2f} | "
            f"unrealized=${summary['unrealized_pnl']:.2f} | "
            f"signals={new_signals} | top_momentum={top_momentum:.3f}"
        )

        return {
            "signals": signals_path,
            "orders": orders_path,
            "positions": positions_path,
            "signal_history": signal_history_path,
            "exits": exits_path,
            "ledger": ledger_path,
            "closed_trades": closed_trades_path,
            "performance_breakdown": performance_breakdown_path,
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
