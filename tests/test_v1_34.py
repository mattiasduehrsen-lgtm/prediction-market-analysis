"""
Tests for v1.34 critical paths.

Covers:
  - _recent_trade_wr() in main.py (the ETH-LIVE gate)
  - v1.28 corrected_pnl() logic (share discount + TP override)
  - Brain decisions CSV append (window_brain._append_brain_log)
"""
from __future__ import annotations

import csv
import importlib
from pathlib import Path

import pytest


# ── _recent_trade_wr ──────────────────────────────────────────────────────────

@pytest.fixture
def trades_csv(tmp_path, monkeypatch):
    """Build a temp trades.csv and patch TRADES_FILE so main.py reads it."""
    csv_path = tmp_path / "trades.csv"
    fields = ["position_id", "asset", "window", "strategy", "side",
              "entry_price", "exit_price", "pnl_usd", "exit_reason",
              "opened_at", "closed_at"]
    rows = [
        # 10 closed ETH-15m MR trades — mix of wins / losses
        # Want last 8 to be 5 wins / 3 losses → ETH-15m LIVE gate passes
        # First trade is OLDEST (will be trimmed when we take last 8)
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"-3.00","exit_reason":"soft_exit_stalled","opened_at":"1700"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1701"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1702"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"-3.00","exit_reason":"soft_exit_stalled","opened_at":"1703"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1704"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1705"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"-3.00","exit_reason":"soft_exit_stalled","opened_at":"1706"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1707"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1708"},
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"-3.00","exit_reason":"soft_exit_stalled","opened_at":"1709"},
        # Open trade (should be excluded)
        {"asset":"ETH","window":"15m","strategy":"mean_reversion","pnl_usd":"0","exit_reason":"","opened_at":"1710"},
        # Wrong asset (should be excluded)
        {"asset":"BTC","window":"15m","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1711"},
        # Wrong window (should be excluded)
        {"asset":"ETH","window":"4h","strategy":"mean_reversion","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1712"},
        # Wrong strategy (should be excluded)
        {"asset":"ETH","window":"15m","strategy":"resolution_scalp","pnl_usd":"+5.00","exit_reason":"take_profit","opened_at":"1713"},
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})

    # Patch engine_5m.TRADES_FILE before main.py imports it inside the function
    import src.bot.engine_5m as e
    monkeypatch.setattr(e, "TRADES_FILE", csv_path)
    return csv_path


def test_recent_wr_eth_15m_passes_5_of_8(trades_csv):
    """Last 8 ETH-15m closed MR trades: 5 wins / 3 losses → filter passes (>=5)."""
    import main
    wins, total = main._recent_trade_wr("ETH", "15m", n=8)
    assert total == 8
    assert wins == 5


def test_recent_wr_filters_out_open_trades(trades_csv):
    """The 'open' row at the end of the CSV must not count."""
    import main
    wins, total = main._recent_trade_wr("ETH", "15m", n=8)
    # If open trade leaked in, total would be 8 but wins would shift
    assert wins == 5 and total == 8


def test_recent_wr_excludes_other_assets(trades_csv):
    """BTC row must not affect ETH count."""
    import main
    wins, total = main._recent_trade_wr("BTC", "15m", n=8)
    assert total < 8   # only 1 BTC trade exists, so < 8 → returns (0, n)
    assert wins == 0


def test_recent_wr_excludes_other_windows(trades_csv):
    """4h ETH should not be counted toward 15m."""
    import main
    # ETH-15m fixture has 10 closed trades: 6 wins / 4 losses.
    # If the 4h trade leaked we'd see wins=7 (4h trade is also a win).
    wins, total = main._recent_trade_wr("ETH", "15m", n=10)
    assert total == 10
    assert wins == 6   # 6 wins from ETH-15m; the 4h +5 trade is correctly excluded


def test_recent_wr_insufficient_history(trades_csv):
    """If fewer than N trades exist, returns (0, count) — gate must block."""
    import main
    wins, total = main._recent_trade_wr("SOL", "15m", n=8)  # SOL has 0 trades
    assert (wins, total) == (0, 0)


# ── v1.28 corrected_pnl ──────────────────────────────────────────────────────

def test_corrected_pnl_take_profit():
    """TP trades use take_profit (0.60) not exit_price (which was cur_up like 0.62)."""
    from daily_summary import corrected_pnl
    row = {
        "size_usd": "15.0",
        "entry_price": "0.40",
        "take_profit": "0.60",
        "exit_price": "0.62",   # observed cur_up — over-stated
        "exit_reason": "take_profit",
    }
    pnl = corrected_pnl(row)
    # shares = round(15.0 / 0.40 * 0.955, 2) = round(35.8125, 2) = 35.81
    # pnl = 35.81 * 0.60 - 15.0 = 21.486 - 15.0 = 6.486
    assert pnl == pytest.approx(6.486, abs=0.01)


def test_corrected_pnl_stop_loss():
    """Non-TP exits use the recorded exit_price."""
    from daily_summary import corrected_pnl
    row = {
        "size_usd": "15.0",
        "entry_price": "0.40",
        "take_profit": "0.60",
        "exit_price": "0.10",
        "exit_reason": "hard_stop_floor",
    }
    pnl = corrected_pnl(row)
    # shares = 35.81; pnl = 35.81 * 0.10 - 15 = 3.581 - 15 = -11.419
    assert pnl == pytest.approx(-11.419, abs=0.01)


def test_corrected_pnl_share_discount_applied():
    """Verify the 0.955 discount: without discount we'd get a different number."""
    from daily_summary import corrected_pnl
    row = {
        "size_usd": "15.0",
        "entry_price": "0.40",
        "take_profit": "0.60",
        "exit_price": "0.60",
        "exit_reason": "take_profit",
    }
    pnl_corrected = corrected_pnl(row)
    # Without discount: shares=37.5; pnl = 37.5 * 0.60 - 15 = 22.5 - 15 = 7.50
    # With discount:   shares=35.81; pnl = 35.81 * 0.60 - 15 = 6.486
    # Gap: (37.5 - 35.81) * 0.60 = 1.69 * 0.60 = ~1.01
    naive_pnl = 37.5 * 0.60 - 15.0
    assert pnl_corrected < naive_pnl
    assert (naive_pnl - pnl_corrected) == pytest.approx(1.014, abs=0.05)


def test_corrected_pnl_empty_row():
    """Missing fields default to 0 - shouldn't crash."""
    from daily_summary import corrected_pnl
    assert corrected_pnl({}) == pytest.approx(0.0)


def test_corrected_pnl_zero_entry_price_falls_back():
    """If entry_price is 0, can't compute shares - fall back to recorded pnl_usd."""
    from daily_summary import corrected_pnl
    row = {"entry_price": "0", "pnl_usd": "-3.50", "exit_reason": "soft_exit_stalled"}
    assert corrected_pnl(row) == pytest.approx(-3.50)


# ── Brain CSV append ─────────────────────────────────────────────────────────

def test_append_brain_log_creates_header(tmp_path, monkeypatch):
    """First call should write header + row."""
    import src.bot.window_brain as wb
    test_path = tmp_path / "brain_decisions.csv"
    monkeypatch.setattr(wb, "_BRAIN_LOG_PATH", test_path)
    wb._append_brain_log({
        "timestamp": 1234567.0,
        "asset": "ETH",
        "window": "15m",
        "regime": "ranging",
        "mr_edge": "normal",
        "modifier": 0.0,
    })
    content = test_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("timestamp,asset,window")
    assert "ETH" in lines[1] and "ranging" in lines[1]


def test_append_brain_log_appends(tmp_path, monkeypatch):
    """Subsequent calls should append without re-writing header."""
    import src.bot.window_brain as wb
    test_path = tmp_path / "brain_decisions.csv"
    monkeypatch.setattr(wb, "_BRAIN_LOG_PATH", test_path)
    for i in range(3):
        wb._append_brain_log({"timestamp": float(i), "asset": "BTC", "mr_edge": "degraded"})
    content = test_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 4   # 1 header + 3 rows


def test_append_brain_log_unknown_keys_dropped(tmp_path, monkeypatch):
    """Extra keys in row dict should be silently ignored."""
    import src.bot.window_brain as wb
    test_path = tmp_path / "brain_decisions.csv"
    monkeypatch.setattr(wb, "_BRAIN_LOG_PATH", test_path)
    # 'sneaky_field' is not in _BRAIN_LOG_COLUMNS
    wb._append_brain_log({"timestamp": 1.0, "asset": "ETH", "sneaky_field": "evil"})
    content = test_path.read_text(encoding="utf-8")
    assert "evil" not in content
