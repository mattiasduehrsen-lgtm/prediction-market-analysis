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
    assert saved["summary"].exists()
    assert saved["ledger"].exists()

    orders = pd.read_csv(saved["orders"])
    assert len(orders) == 1
    assert orders.loc[0, "outcome"] == "Yes"

    summary = json.loads(saved["summary"].read_text())
    assert summary["orders"] == 1
    assert summary["positions"] == 1

    ledger = pd.read_csv(saved["ledger"])
    assert len(ledger) == 1
    assert ledger.loc[0, "side"] == "buy"


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
