"""
Paper trading engine for BTC strike markets.

Tracks open positions, processes exits, logs closed trades.
All state is persisted to CSV/JSON so it survives restarts.

Files:
  output/btc_trading/positions.csv   — open positions
  output/btc_trading/trades.csv      — closed trade history
  output/btc_trading/summary.json    — running P&L summary
"""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.bot.signal import TradeSignal

OUT_DIR        = Path("output/btc_trading")
POSITIONS_FILE = OUT_DIR / "positions.csv"
TRADES_FILE    = OUT_DIR / "trades.csv"
SUMMARY_FILE   = OUT_DIR / "summary.json"

STARTING_EQUITY = 1000.0
POSITION_SIZE   = 20.0   # $ per trade (paper)

POSITION_FIELDS = [
    "position_id", "condition_id", "question", "strike", "side",
    "entry_price", "take_profit", "stop_loss", "size_usd", "shares",
    "entry_btc", "entry_momentum_5m", "reason", "opened_at",
]

TRADE_FIELDS = POSITION_FIELDS + [
    "exit_price", "exit_reason", "closed_at",
    "hold_seconds", "pnl_usd", "return_pct",
]


@dataclass
class Position:
    position_id: str
    condition_id: str
    question: str
    strike: int
    side: str            # "YES" or "NO"
    entry_price: float
    take_profit: float
    stop_loss: float
    size_usd: float
    shares: float        # size_usd / entry_price
    entry_btc: float
    entry_momentum_5m: float
    reason: str
    opened_at: float     # unix timestamp


@dataclass
class ClosedTrade:
    position_id: str
    condition_id: str
    question: str
    strike: int
    side: str
    entry_price: float
    take_profit: float
    stop_loss: float
    size_usd: float
    shares: float
    entry_btc: float
    entry_momentum_5m: float
    reason: str
    opened_at: float
    exit_price: float
    exit_reason: str
    closed_at: float
    hold_seconds: float
    pnl_usd: float
    return_pct: float


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _load_positions() -> dict[str, Position]:
    if not POSITIONS_FILE.exists():
        return {}
    positions = {}
    with open(POSITIONS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                p = Position(
                    position_id=row["position_id"],
                    condition_id=row["condition_id"],
                    question=row["question"],
                    strike=int(row["strike"]),
                    side=row["side"],
                    entry_price=float(row["entry_price"]),
                    take_profit=float(row["take_profit"]),
                    stop_loss=float(row["stop_loss"]),
                    size_usd=float(row["size_usd"]),
                    shares=float(row["shares"]),
                    entry_btc=float(row["entry_btc"]),
                    entry_momentum_5m=float(row["entry_momentum_5m"]),
                    reason=row["reason"],
                    opened_at=float(row["opened_at"]),
                )
                positions[p.position_id] = p
            except (KeyError, ValueError):
                pass
    return positions


def _save_positions(positions: dict[str, Position]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(POSITIONS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSITION_FIELDS)
        writer.writeheader()
        for p in positions.values():
            writer.writerow(asdict(p))


def _append_trade(trade: ClosedTrade) -> None:
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
            "equity": STARTING_EQUITY,
            "open_positions": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }
    trades: list[ClosedTrade] = []
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(ClosedTrade(**{
                    k: (float(row[k]) if k not in ("position_id","condition_id","question","side","reason","exit_reason") else row[k])
                    for k in TRADE_FIELDS
                    if k in row
                }))
            except Exception:
                pass

    total_pnl = sum(t.pnl_usd for t in trades)
    wins   = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]

    return {
        "equity": round(STARTING_EQUITY + total_pnl, 2),
        "open_positions": len(_load_positions()),
        "closed_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "total_pnl": round(total_pnl, 2),
        "avg_win":  round(sum(t.pnl_usd for t in wins)   / len(wins),   2) if wins   else 0.0,
        "avg_loss": round(sum(t.pnl_usd for t in losses) / len(losses), 2) if losses else 0.0,
    }


class PaperEngine:
    """Stateful paper trading engine. Instantiate once and reuse across loop iterations."""

    def __init__(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.positions: dict[str, Position] = _load_positions()
        print(f"[PAPER] Loaded {len(self.positions)} open positions")

    def already_in(self, condition_id: str) -> bool:
        """True if we already have an open position in this market."""
        return any(p.condition_id == condition_id for p in self.positions.values())

    def open(self, signal: TradeSignal) -> Position | None:
        """Open a new paper position. Returns the Position or None if already in."""
        if self.already_in(signal.condition_id):
            return None

        shares = POSITION_SIZE / signal.entry_price
        pos = Position(
            position_id=str(uuid.uuid4())[:8],
            condition_id=signal.condition_id,
            question=signal.question,
            strike=signal.strike,
            side=signal.side,
            entry_price=signal.entry_price,
            take_profit=signal.take_profit,
            stop_loss=signal.stop_loss,
            size_usd=POSITION_SIZE,
            shares=shares,
            entry_btc=signal.btc_price,
            entry_momentum_5m=signal.btc_momentum_5m,
            reason=signal.reason,
            opened_at=time.time(),
        )
        self.positions[pos.position_id] = pos
        _save_positions(self.positions)

        print(
            f"[PAPER] OPEN  {pos.position_id} | {pos.side} ${pos.strike:,} "
            f"@ {pos.entry_price:.3f} | BTC={pos.entry_btc:,.0f} | {pos.reason}"
        )
        return pos

    def close(
        self,
        position_id: str,
        current_yes_price: float,
        exit_reason: str,
    ) -> ClosedTrade | None:
        """Close an open position at current_yes_price. Returns ClosedTrade."""
        pos = self.positions.pop(position_id, None)
        if pos is None:
            return None

        exit_price = current_yes_price if pos.side == "YES" else 1 - current_yes_price
        pnl = (exit_price - pos.entry_price) * pos.shares * 100  # USDC cents → dollars
        # Simpler: treat as % return on size_usd
        pnl_usd = (exit_price - pos.entry_price) / pos.entry_price * pos.size_usd
        return_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        hold_sec = time.time() - pos.opened_at

        trade = ClosedTrade(
            **asdict(pos),
            exit_price=exit_price,
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
            f"[PAPER] CLOSE {pos.position_id} | {emoji} ${pnl_usd:+.2f} ({return_pct:+.1f}%) "
            f"| {exit_reason} | hold={hold_sec/60:.1f}min"
        )
        return trade

    def summary(self) -> dict[str, Any]:
        s = _compute_summary()
        s["open_positions"] = len(self.positions)
        return s

    def save_summary(self) -> None:
        s = self.summary()
        SUMMARY_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
