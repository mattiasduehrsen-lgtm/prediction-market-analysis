"""
Paper trading engine for 5-minute Up/Down markets.

Simulates Polymarket's 10% taker fee on both entry and exit.
Positions auto-close 60 seconds before each window expires.

Files:
  output/5m_trading/positions.csv   — open positions
  output/5m_trading/trades.csv      — closed trade history
  output/5m_trading/summary.json    — running P&L summary
"""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT_DIR        = Path("output/5m_trading")
POSITIONS_FILE = OUT_DIR / "positions.csv"
TRADES_FILE    = OUT_DIR / "trades.csv"
SUMMARY_FILE   = OUT_DIR / "summary.json"

STARTING_EQUITY = 1000.0
POSITION_SIZE   = 20.0    # $ per trade (paper)
TAKER_FEE       = 0.10    # 10% simulated taker fee each way

POSITION_FIELDS = [
    "position_id", "condition_id", "slug", "asset", "side",
    "entry_price", "take_profit", "stop_loss",
    "size_usd", "shares", "entry_fee_usd",
    "window_end_ts", "opened_at",
]

TRADE_FIELDS = POSITION_FIELDS + [
    "exit_price", "exit_fee_usd", "exit_reason",
    "closed_at", "hold_seconds", "pnl_usd", "return_pct",
]


@dataclass
class Position5m:
    position_id: str
    condition_id: str
    slug: str
    asset: str
    side: str           # "UP" or "DOWN"
    entry_price: float  # price paid per share (after spread, before fee)
    take_profit: float  # price at which we exit with profit
    stop_loss: float    # price at which we cut loss
    size_usd: float     # gross position size
    shares: float       # effective shares after entry fee deducted
    entry_fee_usd: float
    window_end_ts: float
    opened_at: float


@dataclass
class ClosedTrade5m:
    position_id: str
    condition_id: str
    slug: str
    asset: str
    side: str
    entry_price: float
    take_profit: float
    stop_loss: float
    size_usd: float
    shares: float
    entry_fee_usd: float
    window_end_ts: float
    opened_at: float
    exit_price: float
    exit_fee_usd: float
    exit_reason: str
    closed_at: float
    hold_seconds: float
    pnl_usd: float
    return_pct: float


def _load_positions() -> dict[str, Position5m]:
    if not POSITIONS_FILE.exists():
        return {}
    positions: dict[str, Position5m] = {}
    with open(POSITIONS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                p = Position5m(
                    position_id=row["position_id"],
                    condition_id=row["condition_id"],
                    slug=row["slug"],
                    asset=row["asset"],
                    side=row["side"],
                    entry_price=float(row["entry_price"]),
                    take_profit=float(row["take_profit"]),
                    stop_loss=float(row["stop_loss"]),
                    size_usd=float(row["size_usd"]),
                    shares=float(row["shares"]),
                    entry_fee_usd=float(row["entry_fee_usd"]),
                    window_end_ts=float(row["window_end_ts"]),
                    opened_at=float(row["opened_at"]),
                )
                positions[p.position_id] = p
            except (KeyError, ValueError):
                pass
    return positions


def _save_positions(positions: dict[str, Position5m]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSITION_FIELDS)
        writer.writeheader()
        for p in positions.values():
            writer.writerow(asdict(p))


def _append_trade(trade: ClosedTrade5m) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not TRADES_FILE.exists()
    with open(TRADES_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(asdict(trade))


def _compute_summary() -> dict[str, Any]:
    if not TRADES_FILE.exists():
        return {
            "equity": STARTING_EQUITY, "closed_trades": 0,
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        }
    trades: list[ClosedTrade5m] = []
    str_fields = {"position_id","condition_id","slug","asset","side","exit_reason"}
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(ClosedTrade5m(**{
                    k: (row[k] if k in str_fields else float(row[k]))
                    for k in TRADE_FIELDS if k in row
                }))
            except Exception:
                pass

    total_pnl = sum(t.pnl_usd for t in trades)
    wins   = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]

    return {
        "equity":       round(STARTING_EQUITY + total_pnl, 2),
        "closed_trades": len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "total_pnl":     round(total_pnl, 2),
        "avg_win":       round(sum(t.pnl_usd for t in wins)   / len(wins),   2) if wins   else 0.0,
        "avg_loss":      round(sum(t.pnl_usd for t in losses) / len(losses), 2) if losses else 0.0,
    }


class Engine5m:
    """Paper trading engine for 5-minute up/down markets."""

    def __init__(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.positions: dict[str, Position5m] = _load_positions()
        print(f"[ENGINE5M] Loaded {len(self.positions)} open positions")

    def already_in(self, condition_id: str) -> bool:
        return any(p.condition_id == condition_id for p in self.positions.values())

    def open(
        self,
        condition_id: str,
        slug: str,
        asset: str,
        side: str,           # "UP" or "DOWN"
        entry_price: float,
        take_profit: float,
        stop_loss: float,
        window_end_ts: float,
    ) -> Position5m | None:
        if self.already_in(condition_id):
            return None

        # Simulate taker fee: deducted from gross position size at entry
        entry_fee = POSITION_SIZE * TAKER_FEE
        net_investment = POSITION_SIZE - entry_fee
        shares = net_investment / entry_price

        pos = Position5m(
            position_id=str(uuid.uuid4())[:8],
            condition_id=condition_id,
            slug=slug,
            asset=asset,
            side=side,
            entry_price=entry_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            size_usd=POSITION_SIZE,
            shares=shares,
            entry_fee_usd=round(entry_fee, 4),
            window_end_ts=window_end_ts,
            opened_at=time.time(),
        )
        self.positions[pos.position_id] = pos
        _save_positions(self.positions)

        secs = max(0, window_end_ts - time.time())
        print(
            f"[ENGINE5M] OPEN  {pos.position_id} | {asset} {side} "
            f"@ {entry_price:.3f} | tp={take_profit:.3f} sl={stop_loss:.3f} "
            f"| {secs:.0f}s left"
        )
        return pos

    def close(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
    ) -> ClosedTrade5m | None:
        pos = self.positions.pop(position_id, None)
        if pos is None:
            return None

        # Simulate taker fee on exit: deducted from gross exit proceeds
        gross_proceeds = pos.shares * exit_price
        exit_fee = gross_proceeds * TAKER_FEE
        net_proceeds = gross_proceeds - exit_fee

        pnl_usd    = net_proceeds - pos.size_usd  # net vs gross invested
        return_pct = pnl_usd / pos.size_usd * 100
        hold_sec   = time.time() - pos.opened_at

        trade = ClosedTrade5m(
            **asdict(pos),
            exit_price=exit_price,
            exit_fee_usd=round(exit_fee, 4),
            exit_reason=exit_reason,
            closed_at=time.time(),
            hold_seconds=round(hold_sec, 1),
            pnl_usd=round(pnl_usd, 4),
            return_pct=round(return_pct, 2),
        )
        _append_trade(trade)
        _save_positions(self.positions)

        emoji = "WIN " if pnl_usd > 0 else "LOSS"
        print(
            f"[ENGINE5M] CLOSE {pos.position_id} | {emoji} ${pnl_usd:+.2f} ({return_pct:+.1f}%) "
            f"| {exit_reason} | hold={hold_sec:.0f}s"
        )
        return trade

    def summary(self) -> dict[str, Any]:
        s = _compute_summary()
        s["open_positions"] = len(self.positions)
        return s

    def save_summary(self) -> None:
        s = self.summary()
        SUMMARY_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
