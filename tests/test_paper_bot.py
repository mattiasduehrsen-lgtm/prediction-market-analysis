from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.bot.polymarket import PaperTradingBot


def test_paper_bot_run_once(tmp_path: Path):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will Team A win?",
                "slug": "team-a-win",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-03-20T12:00:00+00:00",
                "created_at": "2026-03-19T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1773925200,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1773925260,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
            {
                "condition_id": "cond-1",
                "asset": "no-token",
                "side": "SELL",
                "size": 10.0,
                "price": 0.58,
                "timestamp": 1773925280,
                "outcome": "No",
                "outcome_index": 1,
                "transaction_hash": "tx-3",
            },
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, output_dir=output_dir).run_once()

    assert saved["signals"].exists()
    assert saved["orders"].exists()
    assert saved["positions"].exists()
    assert saved["signal_history"].exists()
    assert saved["summary"].exists()
    assert saved["ledger"].exists()
    assert saved["closed_trades"].exists()
    assert saved["performance_breakdown"].exists()

    orders = pd.read_csv(saved["orders"])
    assert len(orders) == 1
    assert orders.loc[0, "outcome"] == "Yes"
    assert orders.loc[0, "reason"].startswith("edge=")
    assert orders.loc[0, "conviction"] > 0
    assert orders.loc[0, "signal_runs"] >= 1

    summary = json.loads(saved["summary"].read_text())
    assert summary["orders"] == 1
    assert summary["positions"] == 1
    assert "realized_pnl" in summary
    assert "unrealized_pnl" in summary
    assert "first_entry_avg_realized_pnl" in summary
    assert "later_entry_avg_realized_pnl" in summary

    ledger = pd.read_csv(saved["ledger"])
    assert len(ledger) == 1
    assert ledger.loc[0, "side"] == "buy"
    assert "position_id" in ledger.columns


def test_paper_bot_persists_and_exits(tmp_path: Path):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()

    markets_open = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will Team A win?",
                "slug": "team-a-win",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-03-20T12:00:00+00:00",
                "created_at": "2026-03-19T12:00:00+00:00",
            }
        ]
    )
    trades_open = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1773925200,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1773925260,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )

    markets_open.to_csv(data_dir / "markets.csv", index=False)
    trades_open.to_csv(data_dir / "trades.csv", index=False)
    PaperTradingBot(data_dir=data_dir, output_dir=output_dir).run_once()

    markets_exit = markets_open.copy()
    markets_exit["outcome_prices"] = "[0.30, 0.70]"
    trades_exit = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "SELL",
                "size": 40.0,
                "price": 0.30,
                "timestamp": 1773928860,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-3",
            }
        ]
    )

    markets_exit.to_csv(data_dir / "markets.csv", index=False)
    trades_exit.to_csv(data_dir / "trades.csv", index=False)
    saved = PaperTradingBot(data_dir=data_dir, output_dir=output_dir).run_once()

    orders = pd.read_csv(saved["orders"])
    assert set(orders["side"]) == {"sell"}
    assert orders.loc[0, "reason"] in {"edge_reversal", "stop_loss", "take_profit"}

    positions = pd.read_csv(saved["positions"])
    assert positions.empty

    summary = json.loads(saved["summary"].read_text())
    assert summary["positions"] == 0
    assert summary["cash"] < 1000.0

    ledger = pd.read_csv(saved["ledger"])
    assert set(ledger["side"]) == {"buy", "sell"}
    assert len(ledger) == 2

    closed_trades = pd.read_csv(saved["closed_trades"])
    assert len(closed_trades) == 1
    assert closed_trades.loc[0, "realized_pnl"] < 0


def test_paper_bot_loop_appends_no_duplicate_orders(tmp_path: Path):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will Team A win?",
                "slug": "team-a-win",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-03-20T12:00:00+00:00",
                "created_at": "2026-03-19T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1773925200,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1773925260,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, output_dir=output_dir).run_loop(iterations=2, sleep_seconds=0)

    orders = pd.read_csv(saved["orders"])
    ledger = pd.read_csv(saved["ledger"])
    positions = pd.read_csv(saved["positions"])

    assert len(orders) == 1
    assert set(orders["side"]) == {"buy"}
    assert len(ledger) == 1
    assert len(positions) == 1


def test_paper_bot_uses_kalshi_confirmation_for_polymarket_entry(tmp_path: Path):
    data_dir = tmp_path / "data"
    kalshi_dir = tmp_path / "kalshi"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    kalshi_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will Team A win tonight?",
                "slug": "team-a-win",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-03-20T12:00:00+00:00",
                "created_at": "2026-03-19T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1773925200,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1773925260,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )
    kalshi_markets = pd.DataFrame(
        [
            {
                "ticker": "TEAM-A",
                "title": "Will Team A win tonight?",
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "yes_bid": 57,
                "yes_ask": 59,
                "last_price": 58,
                "volume": 3000,
                "open_interest": 1000,
                "close_time": "2026-03-20T10:00:00+00:00",
            }
        ]
    )
    kalshi_trades = pd.DataFrame(
        [
            {
                "trade_id": "k1",
                "ticker": "TEAM-A",
                "count": 2,
                "yes_price": 59,
                "no_price": 41,
                "taker_side": "yes",
                "created_time": "2026-03-19T13:01:00+00:00",
            }
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)
    kalshi_markets.to_csv(kalshi_dir / "markets.csv", index=False)
    kalshi_trades.to_csv(kalshi_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, kalshi_data_dir=kalshi_dir, output_dir=output_dir).run_once()

    signals = pd.read_csv(saved["signals"])
    orders = pd.read_csv(saved["orders"])

    assert len(orders) == 1
    assert bool(signals.loc[0, "kalshi_match_found"])
    assert bool(signals.loc[0, "kalshi_confirms"])
    assert float(signals.loc[0, "cross_market_support"]) > 0
    assert "kalshi_confirms" in orders.loc[0, "reason"]
    assert float(orders.loc[0, "kalshi_match_score"]) > 0
    assert float(orders.loc[0, "cross_market_support"]) > 0
    assert "kalshi_confirms" in orders.loc[0, "cross_market_reason"]
    assert orders.loc[0, "kalshi_match_bucket"] in {"medium", "high"}
    assert orders.loc[0, "cross_market_support_bucket"] in {"confirm", "strong_confirm"}


def test_paper_bot_skips_bad_cross_market_match(tmp_path: Path):
    data_dir = tmp_path / "data"
    kalshi_dir = tmp_path / "kalshi"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    kalshi_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will CPI be above 3 in 2026?",
                "slug": "cpi-3-2026",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-03-20T12:00:00+00:00",
                "created_at": "2026-03-19T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1773925200,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1773925260,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )
    kalshi_markets = pd.DataFrame(
        [
            {
                "ticker": "CPI-4",
                "title": "Will CPI be above 4 in 2026?",
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "yes_bid": 57,
                "yes_ask": 59,
                "last_price": 58,
                "volume": 3000,
                "open_interest": 1000,
                "close_time": "2026-03-20T10:00:00+00:00",
            }
        ]
    )
    kalshi_trades = pd.DataFrame(
        [
            {
                "trade_id": "k1",
                "ticker": "CPI-4",
                "count": 2,
                "yes_price": 59,
                "no_price": 41,
                "taker_side": "yes",
                "created_time": "2026-03-19T13:01:00+00:00",
            }
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)
    kalshi_markets.to_csv(kalshi_dir / "markets.csv", index=False)
    kalshi_trades.to_csv(kalshi_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, kalshi_data_dir=kalshi_dir, output_dir=output_dir).run_once()
    signals = pd.read_csv(saved["signals"])

    assert not bool(signals.loc[0, "kalshi_match_found"])
    assert signals.loc[0, "cross_market_reason"] == "no_kalshi_match"


def test_paper_bot_matches_sports_aliases_across_markets(tmp_path: Path):
    data_dir = tmp_path / "data"
    kalshi_dir = tmp_path / "kalshi"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    kalshi_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will Kansas City beat Philadelphia?",
                "slug": "kc-vs-philly",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-03-20T12:00:00+00:00",
                "created_at": "2026-03-19T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1773925200,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1773925260,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )
    kalshi_markets = pd.DataFrame(
        [
            {
                "ticker": "NFL-KC-PHI",
                "title": "Will the Chiefs defeat the Eagles?",
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "yes_bid": 57,
                "yes_ask": 59,
                "last_price": 58,
                "volume": 3000,
                "open_interest": 1000,
                "close_time": "2026-03-20T10:00:00+00:00",
            }
        ]
    )
    kalshi_trades = pd.DataFrame(
        [
            {
                "trade_id": "k1",
                "ticker": "NFL-KC-PHI",
                "count": 2,
                "yes_price": 59,
                "no_price": 41,
                "taker_side": "yes",
                "created_time": "2026-03-19T13:01:00+00:00",
            }
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)
    kalshi_markets.to_csv(kalshi_dir / "markets.csv", index=False)
    kalshi_trades.to_csv(kalshi_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, kalshi_data_dir=kalshi_dir, output_dir=output_dir).run_once()
    signals = pd.read_csv(saved["signals"])

    assert bool(signals.loc[0, "kalshi_match_found"])
    assert float(signals.loc[0, "kalshi_match_score"]) >= 0.6
    assert "domain=" in signals.loc[0, "kalshi_match_components"]


def test_paper_bot_matches_politics_name_and_date(tmp_path: Path):
    data_dir = tmp_path / "data"
    kalshi_dir = tmp_path / "kalshi"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    kalshi_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will Trump win Iowa on Jan 15?",
                "slug": "trump-iowa-jan15",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-01-15T23:00:00+00:00",
                "created_at": "2026-01-14T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1768482000,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1768482060,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )
    kalshi_markets = pd.DataFrame(
        [
            {
                "ticker": "POL-IA-TRUMP",
                "title": "Will Donald Trump win Iowa on January 15?",
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "yes_bid": 57,
                "yes_ask": 59,
                "last_price": 58,
                "volume": 3000,
                "open_interest": 1000,
                "close_time": "2026-01-15T22:00:00+00:00",
            }
        ]
    )
    kalshi_trades = pd.DataFrame(
        [
            {
                "trade_id": "k1",
                "ticker": "POL-IA-TRUMP",
                "count": 2,
                "yes_price": 59,
                "no_price": 41,
                "taker_side": "yes",
                "created_time": "2026-01-15T13:01:00+00:00",
            }
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)
    kalshi_markets.to_csv(kalshi_dir / "markets.csv", index=False)
    kalshi_trades.to_csv(kalshi_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, kalshi_data_dir=kalshi_dir, output_dir=output_dir).run_once()
    signals = pd.read_csv(saved["signals"])

    assert bool(signals.loc[0, "kalshi_match_found"])
    assert float(signals.loc[0, "kalshi_match_score"]) >= 0.6
    assert "domain=" in signals.loc[0, "cross_market_reason"]


def test_paper_bot_matches_economics_threshold_market(tmp_path: Path):
    data_dir = tmp_path / "data"
    kalshi_dir = tmp_path / "kalshi"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    kalshi_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will CPI be above 3 in 2026?",
                "slug": "cpi-3-2026",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-03-20T12:00:00+00:00",
                "created_at": "2026-03-19T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1773925200,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1773925260,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )
    kalshi_markets = pd.DataFrame(
        [
            {
                "ticker": "CPI-3",
                "title": "Will inflation be above 3 in 2026?",
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "yes_bid": 57,
                "yes_ask": 59,
                "last_price": 58,
                "volume": 3000,
                "open_interest": 1000,
                "close_time": "2026-03-20T10:00:00+00:00",
            }
        ]
    )
    kalshi_trades = pd.DataFrame(
        [
            {
                "trade_id": "k1",
                "ticker": "CPI-3",
                "count": 2,
                "yes_price": 59,
                "no_price": 41,
                "taker_side": "yes",
                "created_time": "2026-03-19T13:01:00+00:00",
            }
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)
    kalshi_markets.to_csv(kalshi_dir / "markets.csv", index=False)
    kalshi_trades.to_csv(kalshi_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, kalshi_data_dir=kalshi_dir, output_dir=output_dir).run_once()
    signals = pd.read_csv(saved["signals"])

    assert bool(signals.loc[0, "kalshi_match_found"])
    assert float(signals.loc[0, "kalshi_match_score"]) >= 0.6


def test_paper_bot_matches_crypto_threshold_market(tmp_path: Path):
    data_dir = tmp_path / "data"
    kalshi_dir = tmp_path / "kalshi"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    kalshi_dir.mkdir()

    markets = pd.DataFrame(
        [
            {
                "id": "m1",
                "condition_id": "cond-1",
                "question": "Will Bitcoin be above 100000 by Dec 31 2026?",
                "slug": "btc-100k-dec31",
                "outcomes": '["Yes", "No"]',
                "outcome_prices": "[0.42, 0.58]",
                "clob_token_ids": '["yes-token", "no-token"]',
                "volume": 20000.0,
                "liquidity": 5000.0,
                "active": True,
                "closed": False,
                "end_date": "2026-12-31T23:00:00+00:00",
                "created_at": "2026-12-30T12:00:00+00:00",
            }
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 50.0,
                "price": 0.48,
                "timestamp": 1798722000,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-1",
            },
            {
                "condition_id": "cond-1",
                "asset": "yes-token",
                "side": "BUY",
                "size": 30.0,
                "price": 0.49,
                "timestamp": 1798722060,
                "outcome": "Yes",
                "outcome_index": 0,
                "transaction_hash": "tx-2",
            },
        ]
    )
    kalshi_markets = pd.DataFrame(
        [
            {
                "ticker": "BTC-100K",
                "title": "Will BTC be above 100000 by December 31 2026?",
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "yes_bid": 57,
                "yes_ask": 59,
                "last_price": 58,
                "volume": 3000,
                "open_interest": 1000,
                "close_time": "2026-12-31T22:00:00+00:00",
            }
        ]
    )
    kalshi_trades = pd.DataFrame(
        [
            {
                "trade_id": "k1",
                "ticker": "BTC-100K",
                "count": 2,
                "yes_price": 59,
                "no_price": 41,
                "taker_side": "yes",
                "created_time": "2026-12-31T13:01:00+00:00",
            }
        ]
    )

    markets.to_csv(data_dir / "markets.csv", index=False)
    trades.to_csv(data_dir / "trades.csv", index=False)
    kalshi_markets.to_csv(kalshi_dir / "markets.csv", index=False)
    kalshi_trades.to_csv(kalshi_dir / "trades.csv", index=False)

    saved = PaperTradingBot(data_dir=data_dir, kalshi_data_dir=kalshi_dir, output_dir=output_dir).run_once()
    signals = pd.read_csv(saved["signals"])

    assert bool(signals.loc[0, "kalshi_match_found"])
    assert float(signals.loc[0, "kalshi_match_score"]) >= 0.6
